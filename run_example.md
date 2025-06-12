
** Blur Single Face **
source .venv/bin/activate && python blur_faces.py media/friends.mp4 --mode one --in-face-file media/Ross_Geller.jpg --censor-type pixelation

** Blur Multiple Faces **
python blur_faces.py media/friends.mp4 --mode one \
  --in-face-file media/Ross_Geller.jpg \
  --in-face-file media/Monica_Geller.png \
  --censor-type pixelation