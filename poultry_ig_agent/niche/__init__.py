"""Ниша плагиндери. Жаңы ниша кошуу: niche/<аты>.py түзүп, NICHE өзгөрмөсүн аныктап, REGISTRY'ге кош."""
from .base import Niche
from .poultry import NICHE as POULTRY

REGISTRY = {"poultry": POULTRY}


def get(name="poultry"):
    return REGISTRY[name]
