"""Кадр тандоонун жалпы эрежелери: маани, монетизация жана шаблонго каршы (s2, s5 жана AI баалоо колдонот).

Колдонуучунун талабы (2026-11-20): кадрлардын маанисин жакшыртуу, YouTube монетизация эрежелерин сактоо,
шаблондук (кайталанма) контенттен качуу. Video_001'де «инфраструктура», «прожектор» сыяктуу метафоралар
түз маанисинде изделип, Эркиндик айкели, фэнтези-арт, Halloween мультфильми чыккан.
"""

# Шаблон сток-кадрлар: сценарийде түз айтылбаса колдонулбайт
CLICHES = ("chess pieces", "handshake", "light bulb", "puzzle pieces", "statue", "monument", "businessman on phone",
           "man jumping on mountain top", "sunset silhouette", "stairs to success", "target with arrow",
           "money falling", "trophy", "fireworks", "abstract particles", "kaleidoscope")

VISUAL_RULES = """Visual rules (strict):
- Show the MEANING through a concrete, filmable real-life situation: people, their emotions and actions,
  everyday places and objects. Abstract ideas and metaphors must become a human moment
  (e.g. "living for others' approval" -> a woman rehearsing a smile in a mirror), never a literal picture
  of the metaphor word (no construction sites for "inner infrastructure", no spotlights for "spotlight").
- Live-action footage only: NO cartoons, animation, illustrations, 3D/CGI fantasy, clip-art.
- Advertiser-friendly: NO brands or logos, celebrities, famous landmarks or statues, flags, holiday themes,
  religious symbols, weapons, blood/violence, alcohol focus, sexual content, readable text.
- Avoid generic stock cliches unless the sentence literally mentions them: {cliches}.
- Variety: each visual idea must differ from the others (mix close-ups of faces/hands, medium shots,
  wide environments, meaningful object details); never repeat the same idea in one video.
""".format(cliches=", ".join(CLICHES))
