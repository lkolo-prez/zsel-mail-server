"""
ZSEL Mail Provisioner - Automatyczne zarządzanie skrzynkami email.

Nasłuchuje zmian w FreeIPA i automatycznie:
- Tworzy skrzynki dla nowych użytkowników
- Archiwizuje skrzynki dezaktywowanych
- Aktualizuje aliasy grupowe
"""

import asyncio
import logging
from typing import Optional
from dataclasses import dataclass
from enum import Enum

import ldap3
from ldap3 import Server, Connection, SUBTREE, MODIFY_REPLACE

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class UserRole(Enum):
    """Role użytkowników w systemie."""
    UCZEN = "uczen"
    NAUCZYCIEL = "nauczyciel"
    ADMINISTRACJA = "administracja"
    DYREKCJA = "dyrekcja"


@dataclass
class MailConfig:
    """Konfiguracja serwera pocztowego."""
    domain: str = "zsel.opole.pl"
    maildir_base: str = "/var/mail/vhosts"
    
    # Quota w bajtach
    quota_uczen: int = 1 * 1024 * 1024 * 1024  # 1 GB
    quota_nauczyciel: int = 5 * 1024 * 1024 * 1024  # 5 GB
    quota_admin: int = 10 * 1024 * 1024 * 1024  # 10 GB
    quota_dyrekcja: int = 20 * 1024 * 1024 * 1024  # 20 GB


@dataclass
class FreeIPAConfig:
    """Konfiguracja połączenia z FreeIPA."""
    server: str = "ipa1.zsel.opole.pl"
    base_dn: str = "dc=zsel,dc=opole,dc=pl"
    bind_dn: str = "uid=mail-provisioner,cn=sysaccounts,cn=etc,dc=zsel,dc=opole,dc=pl"
    bind_password: str = ""  # Z env lub secret
    
    # OU do obserwowania
    watch_ous: tuple = (
        "ou=uczniowie",
        "ou=nauczyciele", 
        "ou=administracja",
    )


class MailboxManager:
    """Zarządzanie skrzynkami pocztowymi."""
    
    def __init__(self, config: MailConfig):
        self.config = config
        
    async def create_mailbox(self, uid: str, role: UserRole) -> str:
        """
        Tworzy nową skrzynkę pocztową.
        
        Args:
            uid: Login użytkownika (np. 'jkowalski')
            role: Rola użytkownika
            
        Returns:
            Adres email (np. 'jkowalski@zsel.opole.pl')
        """
        email = f"{uid}@{self.config.domain}"
        quota = self._get_quota(role)
        
        # Tutaj integracja z Dovecot
        # doveadm mailbox create -u {email}
        logger.info(f"Tworzenie skrzynki: {email} (quota: {quota} bytes)")
        
        # TODO: Implementacja
        # - Utwórz maildir
        # - Ustaw quota
        # - Zarejestruj w bazie Dovecot
        
        return email
        
    async def archive_mailbox(self, uid: str) -> str:
        """
        Archiwizuje skrzynkę (read-only).
        
        Args:
            uid: Login użytkownika
            
        Returns:
            Ścieżka do archiwum
        """
        email = f"{uid}@{self.config.domain}"
        archive_path = f"/archive/mail/{uid}"
        
        logger.info(f"Archiwizacja skrzynki: {email} -> {archive_path}")
        
        # TODO: Implementacja
        # - Backup maildir do archive
        # - Ustaw read-only
        # - Wyłącz dostarczanie nowych wiadomości
        
        return archive_path
        
    async def delete_mailbox(self, uid: str) -> None:
        """
        Permanentnie usuwa skrzynkę (po okresie retencji).
        
        Args:
            uid: Login użytkownika
        """
        email = f"{uid}@{self.config.domain}"
        logger.warning(f"Permanentne usunięcie skrzynki: {email}")
        
        # TODO: Implementacja
        # - Sprawdź czy minął okres retencji
        # - Usuń archiwum
        # - Usuń z bazy Dovecot
        
    def _get_quota(self, role: UserRole) -> int:
        """Zwraca quota dla danej roli."""
        quotas = {
            UserRole.UCZEN: self.config.quota_uczen,
            UserRole.NAUCZYCIEL: self.config.quota_nauczyciel,
            UserRole.ADMINISTRACJA: self.config.quota_admin,
            UserRole.DYREKCJA: self.config.quota_dyrekcja,
        }
        return quotas.get(role, self.config.quota_uczen)


class FreeIPAListener:
    """
    Nasłuchuje zmian w FreeIPA przez LDAP.
    
    Używa LDAP persistent search lub polling do wykrywania:
    - Nowych użytkowników
    - Dezaktywowanych użytkowników
    - Usuniętych użytkowników
    - Zmian w grupach (aliasy)
    """
    
    def __init__(
        self, 
        freeipa_config: FreeIPAConfig,
        mailbox_manager: MailboxManager
    ):
        self.config = freeipa_config
        self.mailbox_manager = mailbox_manager
        self.connection: Optional[Connection] = None
        
    async def connect(self) -> None:
        """Nawiązuje połączenie z FreeIPA LDAP."""
        server = Server(self.config.server, use_ssl=True)
        self.connection = Connection(
            server,
            user=self.config.bind_dn,
            password=self.config.bind_password,
            auto_bind=True
        )
        logger.info(f"Połączono z FreeIPA: {self.config.server}")
        
    async def watch_users(self) -> None:
        """Główna pętla obserwująca zmiany użytkowników."""
        if not self.connection:
            await self.connect()
            
        while True:
            try:
                # Sprawdź nowych użytkowników bez atrybutu mail
                await self._process_new_users()
                
                # Sprawdź dezaktywowanych
                await self._process_disabled_users()
                
                # Odśwież aliasy grupowe
                await self._update_group_aliases()
                
            except Exception as e:
                logger.error(f"Błąd w watch loop: {e}")
                
            # Poll co 60 sekund
            await asyncio.sleep(60)
            
    async def _process_new_users(self) -> None:
        """Znajduje i przetwarza nowych użytkowników bez email."""
        for ou in self.config.watch_ous:
            search_base = f"{ou},{self.config.base_dn}"
            
            self.connection.search(
                search_base=search_base,
                search_filter="(&(objectClass=person)(!(mail=*)))",
                search_scope=SUBTREE,
                attributes=['uid', 'cn', 'givenName', 'sn']
            )
            
            for entry in self.connection.entries:
                uid = entry.uid.value
                role = self._detect_role(ou)
                
                logger.info(f"Nowy użytkownik bez email: {uid} (rola: {role})")
                
                # Utwórz skrzynkę
                email = await self.mailbox_manager.create_mailbox(uid, role)
                
                # Zaktualizuj atrybut mail w FreeIPA
                await self._update_mail_attribute(entry.entry_dn, email)
                
    async def _process_disabled_users(self) -> None:
        """Znajduje i przetwarza dezaktywowanych użytkowników."""
        search_base = self.config.base_dn
        
        # Szukaj użytkowników z nsAccountLock=TRUE
        self.connection.search(
            search_base=search_base,
            search_filter="(&(objectClass=person)(nsAccountLock=TRUE)(mail=*))",
            search_scope=SUBTREE,
            attributes=['uid', 'mail', 'nsAccountLock']
        )
        
        for entry in self.connection.entries:
            uid = entry.uid.value
            
            # Sprawdź czy już zarchiwizowany (marker)
            # TODO: Sprawdź w bazie archiwum
            
            logger.info(f"Dezaktywowany użytkownik: {uid}")
            await self.mailbox_manager.archive_mailbox(uid)
            
    async def _update_group_aliases(self) -> None:
        """Aktualizuje aliasy grupowe na podstawie OU."""
        # Dla każdej klasy utwórz alias
        # np. klasa-1ti-2026@zsel.opole.pl -> wszyscy z ou=1ti-2026
        
        # TODO: Implementacja
        pass
        
    async def _update_mail_attribute(self, user_dn: str, email: str) -> None:
        """Aktualizuje atrybut mail użytkownika w FreeIPA."""
        self.connection.modify(
            user_dn,
            {'mail': [(MODIFY_REPLACE, [email])]}
        )
        logger.info(f"Zaktualizowano mail dla {user_dn}: {email}")
        
    def _detect_role(self, ou: str) -> UserRole:
        """Wykrywa rolę na podstawie OU."""
        if "uczniowie" in ou:
            return UserRole.UCZEN
        elif "nauczyciele" in ou:
            return UserRole.NAUCZYCIEL
        elif "administracja" in ou:
            return UserRole.ADMINISTRACJA
        elif "dyrekcja" in ou:
            return UserRole.DYREKCJA
        return UserRole.UCZEN


async def main():
    """Główna funkcja uruchamiająca provisioner."""
    import os
    
    freeipa_config = FreeIPAConfig(
        bind_password=os.environ.get("FREEIPA_PASSWORD", "")
    )
    mail_config = MailConfig()
    
    mailbox_manager = MailboxManager(mail_config)
    listener = FreeIPAListener(freeipa_config, mailbox_manager)
    
    logger.info("Uruchamianie ZSEL Mail Provisioner...")
    await listener.watch_users()


if __name__ == "__main__":
    asyncio.run(main())
