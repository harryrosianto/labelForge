# LabelForge Roadmap

## Fase 1: MVP Auto Labeling
Project & class management (text prompt + exemplar visual), upload gambar (multi-file/ZIP,
thumbnail, deteksi duplikat), auto-labeling zero-shot (Grounding DINO, OWLv2 text &
image-guided, remote inference server), CLI uji model, annotation editor dengan shortcut,
export YOLO & COCO.

## Fase 2: Dataset management
Versioning dataset (snapshot immutable), augmentasi, statistik class balance & ukuran box,
ekstraksi frame dari video/RTSP, import dataset YOLO/COCO yang sudah ada, export sebagai job
di worker, review massal berdasarkan filter, dan audit sampel acak kualitas label.

## Fase 3: Siklus model dengan Google Colab
Training dijalankan di Google Colab, bukan di LabelForge. LabelForge menyiapkan data yang
jujur untuk dievaluasi dan memakai kembali model hasil training:
split per segmen waktu per kamera (frame tetangga dan salinan frame tidak terpisah ke train
dan val), template notebook Colab per versi (Ultralytics YOLO, evaluasi, export ONNX),
provider auto-label dari model ONNX hasil Colab (inference `onnxruntime` di CPU), antrian
review untuk gambar yang hasil modelnya tidak cocok dengan label, dan catatan model per versi
dataset (asal versi dan mAP) untuk membandingkan hasil antar versi.

## Fase 4: Produktivitas review & deploy
Mode review grid (thumbnail dengan box, tandai yang salah lalu approve sisanya), antrian
review berdasarkan confidence rendah, inference playground untuk model ONNX, multi-user
dengan role annotator/reviewer, dan segmentasi dengan SAM.
