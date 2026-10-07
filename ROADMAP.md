# LabelForge Roadmap

## Fase 1: MVP Auto Labeling
Project & class management (text prompt + exemplar visual), upload gambar (multi-file/ZIP,
thumbnail, deteksi duplikat), auto-labeling zero-shot (Grounding DINO, OWLv2 text &
image-guided, remote inference server), CLI uji model, annotation editor dengan shortcut,
export YOLO & COCO.

## Fase 2: Dataset management
Versioning dataset (snapshot immutable), augmentasi, statistik class balance & ukuran box,
ekstraksi frame dari video/RTSP, import dataset YOLO/COCO yang sudah ada.

## Fase 3: Training
Training object detection sebagai background job dari dataset version tertentu (framework
dipilih dengan memperhatikan lisensi), dashboard metrik (mAP,
precision/recall, loss, confusion matrix), model registry, dan model-assisted labeling
(model hasil training menjadi `LabelingProvider`).

## Fase 4: Deploy & active learning
Export ke ONNX/TensorRT/Hailo HEF, inference playground, antrian review berdasarkan
confidence rendah, multi-user dengan role annotator/reviewer, segmentasi dengan SAM.
