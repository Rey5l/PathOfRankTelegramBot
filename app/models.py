from dataclasses import dataclass
from typing import Optional


@dataclass
class Player:
    id: int
    telegram_id: int
    username: str
    rank: str
    level: int
    xp: int
    gold: int
    hp: int
    stamina: int
    attack: int
    defense: int
    luck: int
    current_battle_id: Optional[int]


@dataclass
class Monster:
    id: int
    name: str
    rank: str
    hp: int
    atk: int
    defense: int
    behavior_type: str
    reward_xp: int
    reward_gold: int


@dataclass
class Skill:
    id: int
    name: str
    type: str
    stamina_cost: int
    damage_multiplier: float
    range: str
    effect: str
    rarity: str
    hidden: int
    description: str


@dataclass
class Case:
    id: int
    name: str
    description: str
    min_rolls: int
    max_rolls: int
    weights_json: str
    allow_hidden: int


@dataclass
class Battle:
    id: int
    type: str
    turn: int
    player_action: Optional[str]
    enemy_action: Optional[str]
    log: str
    status: str
    player_id: int
    monster_id: Optional[int]
    enemy_player_id: Optional[int]
    player_hp: int
    player_stamina: int
    enemy_hp: int
    enemy_stamina: int
    position: str
