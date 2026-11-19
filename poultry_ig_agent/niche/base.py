from dataclasses import dataclass, field


@dataclass(frozen=True)
class Niche:
    key: str
    topics: dict                      # topic_key -> {"ky": ..., "ru": ..., "health": bool}
    content_types: dict               # type_key -> сүрөттөмө
    health_terms: tuple               # медициналык тема аныктоочу сөздөр
    trusted_domains: tuple            # ишенимдүү булак домендери (суффикс)
    disclaimers: dict                 # lang -> ветеринар эскертүүсү
    base_hashtags: dict = field(default_factory=dict)   # lang -> [..]
    style_bible: str = ""             # AI видеонун визуалдык шайкештиги үчүн
