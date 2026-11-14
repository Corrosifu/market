"""Réglages communs à tous les services, lus de l'environnement.

Chaque service hérite de `BaseServiceSettings`, fixe son préfixe (`env_prefix`) et ajoute ses champs.
Aucun fichier `.env` n'est lu ici : c'est Docker Compose qui injecte les variables. Aucune valeur secrète par défaut.
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseServiceSettings(BaseSettings):
    """Socle des réglages d'un service : identité, niveau de journalisation, environnement."""

    model_config = SettingsConfigDict(env_file=None, extra="ignore", frozen=True)

    service_name: str
    log_level: str = "INFO"
    environment: str = "local"
