import subprocess, os, sys
sys.path.insert(0, "/home/user/YouTube_Auto_Pipeline")
from poultry_ig_agent import music_gen
U="/root/.claude/uploads/9e8c7630-06f5-5d63-87d2-59c04ddccdf6/"
V1=U+"8f657900-VID-20261109-WA0011.mp4"; V2=U+"d1d350bd-VID-20261109-WA00161.mp4"
OUT="/home/user/YouTube_Auto_Pipeline/poultry_ig_agent/deliveries/Instagram_Reels_05_karagat/"
W="/tmp/claude-0/-home-user-YouTube-Auto-Pipeline/9e8c7630-06f5-5d63-87d2-59c04ddccdf6/scratchpad/kw/"; os.makedirs(W,exist_ok=True)
FB="/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
SEG=[(V1,1.20,7.60,["Карагат көчөттөрү","Добрыня • Селеченская"]),
     (V2,7.60,17.55,["1 жылдык көчөттөр","Тамыры күчтүү, жаңы казылган"]),
     (V2,17.55,25.50,["Баасы — 80 сом","Кийинки жылы мөмө берет"]),
     (V2,49.40,65.00,["Кайда тигилет?","Көлөкө жер: бак түбү, арык жээги"]),
     (V1,31.40,38.00,["Заказ берүү үчүн","Чалыңыз же жазыңыз"]),
     (V2,64.95,70.90,["Күзгү отургузууга","ылайыктуу • Жеткирүү бар"])]
def esc(t): return t.replace("\\","\\\\").replace(":","\\:").replace("'","\u2019").replace("%","\\%")
parts=[]
for i,(src,a,b,lab) in enumerate(SEG):
    d=b-a; o=f"{W}s{i}.mp4"
    txt=(f"drawtext=fontfile={FB}:text='{esc(lab[0])}':fontsize=74:fontcolor=0xffe27a:borderw=5:bordercolor=black@0.85:x=(w-tw)/2:y=170,"
         f"drawtext=fontfile={FB}:text='{esc(lab[1])}':fontsize=50:fontcolor=white:borderw=4:bordercolor=black@0.85:x=(w-tw)/2:y=275,"
         f"drawtext=fontfile={FB}:text='0504 29 29 89':fontsize=56:fontcolor=white:box=1:boxcolor=0x2e7d32@0.92:boxborderw=22:x=(w-tw)/2:y=1600")
    fc=(f"[0:v]fps=30,split[a][b];[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=30:3,eq=brightness=-0.22[bg];"
        f"[b]crop=720:720,scale=1080:1080:flags=lanczos[fg];[bg][fg]overlay=0:420,{txt},fade=t=in:st=0:d=0.2,fade=t=out:st={d-0.2:.2f}:d=0.2,setsar=1[v];"
        f"[0:a]aresample=48000,afade=t=in:st=0:d=0.12,afade=t=out:st={d-0.15:.2f}:d=0.15[au]")
    subprocess.run(["ffmpeg","-v","error","-y","-ss",f"{a}","-t",f"{d}","-i",src,"-filter_complex",fc,"-map","[v]","-map","[au]",
                    "-c:v","libx264","-preset","medium","-crf","20","-c:a","aac","-b:a","160k",o],check=True)
    parts.append(o)
open(W+"list.txt","w").write("".join(f"file '{p}'\n" for p in parts))
subprocess.run(["ffmpeg","-v","error","-y","-f","concat","-safe","0","-i",W+"list.txt","-c","copy",W+"joined.mp4"],check=True)
dur=float(subprocess.check_output(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",W+"joined.mp4"]))
info=music_gen.generate(W+"music.wav",dur,"karagat-reels05","calm")
fc=("[0:a]loudnorm=I=-15:TP=-1.5:LRA=11,asplit[v1][v2];[1:a]volume=0.22[m];"
    "[m][v2]sidechaincompress=threshold=0.03:ratio=6:attack=20:release=400[md];[v1][md]amix=inputs=2:duration=first:normalize=0[a]")
subprocess.run(["ffmpeg","-v","error","-y","-i",W+"joined.mp4","-i",W+"music.wav","-filter_complex",fc,"-map","0:v","-map","[a]",
                "-c:v","copy","-c:a","aac","-b:a","192k","-movflags","+faststart",OUT+"Instagram_Reels_05_karagat.mp4"],check=True)
print(dur,info)
