from pathlib import Path
import random

import numpy as np
import torch
from PIL import Image
from torch.utils.data import Dataset

from .common import load_json, polygons_to_mask


def collate_fn(batch):
  images, targets = zip(*batch)
  return list(images), list(targets)


class CocoInstanceDataset(Dataset):
  def __init__(self, images_dir, annotations_path, random_hflip=0.0):
    self.images_dir = Path(images_dir)
    self.annotations_path = Path(annotations_path)
    self.random_hflip = float(random_hflip)
    self.data = load_json(self.annotations_path)
    self.images = sorted(self.data.get("images", []), key=lambda item: item["id"])
    self.annotations_by_image = {}
    self.categories = sorted(self.data.get("categories", []), key=lambda item: item["id"])
    self.category_id_to_label = {item["id"]: index + 1 for index, item in enumerate(self.categories)}

    for annotation in self.data.get("annotations", []):
      self.annotations_by_image.setdefault(annotation["image_id"], []).append(annotation)

  def __len__(self):
    return len(self.images)

  def _load_image_tensor(self, image_path):
    with Image.open(image_path).convert("RGB") as image:
      array = np.asarray(image, dtype=np.float32) / 255.0
    return torch.from_numpy(array).permute(2, 0, 1)

  def _load_target(self, image_info):
    width = int(image_info["width"])
    height = int(image_info["height"])
    annotations = self.annotations_by_image.get(image_info["id"], [])

    boxes = []
    labels = []
    masks = []
    areas = []
    iscrowd = []

    for annotation in annotations:
      bbox = annotation.get("bbox") or []
      if len(bbox) != 4:
        continue
      x, y, w, h = bbox
      x1 = float(x)
      y1 = float(y)
      x2 = float(x + w)
      y2 = float(y + h)
      if x2 <= x1 or y2 <= y1:
        continue

      segmentation = annotation.get("segmentation") or []
      if not segmentation:
        continue

      mask = polygons_to_mask(width, height, segmentation)
      if int(mask.sum()) <= 0:
        continue

      category_id = annotation.get("category_id")
      if category_id not in self.category_id_to_label:
        continue

      boxes.append([x1, y1, x2, y2])
      labels.append(self.category_id_to_label[category_id])
      masks.append(mask)
      areas.append(float(annotation.get("area") or (w * h)))
      iscrowd.append(int(annotation.get("iscrowd", 0)))

    if boxes:
      boxes_tensor = torch.tensor(boxes, dtype=torch.float32)
      labels_tensor = torch.tensor(labels, dtype=torch.int64)
      masks_tensor = torch.tensor(np.stack(masks), dtype=torch.uint8)
      areas_tensor = torch.tensor(areas, dtype=torch.float32)
      iscrowd_tensor = torch.tensor(iscrowd, dtype=torch.int64)
    else:
      boxes_tensor = torch.zeros((0, 4), dtype=torch.float32)
      labels_tensor = torch.zeros((0,), dtype=torch.int64)
      masks_tensor = torch.zeros((0, height, width), dtype=torch.uint8)
      areas_tensor = torch.zeros((0,), dtype=torch.float32)
      iscrowd_tensor = torch.zeros((0,), dtype=torch.int64)

    return {
      "boxes": boxes_tensor,
      "labels": labels_tensor,
      "masks": masks_tensor,
      "image_id": torch.tensor([int(image_info["id"])], dtype=torch.int64),
      "area": areas_tensor,
      "iscrowd": iscrowd_tensor,
    }

  def _horizontal_flip(self, image_tensor, target):
    width = image_tensor.shape[2]
    flipped_image = torch.flip(image_tensor, dims=[2])
    boxes = target["boxes"].clone()
    if len(boxes):
      boxes[:, 0] = width - target["boxes"][:, 2]
      boxes[:, 2] = width - target["boxes"][:, 0]
    flipped_target = {
      **target,
      "boxes": boxes,
      "masks": torch.flip(target["masks"], dims=[2]),
    }
    return flipped_image, flipped_target

  def __getitem__(self, index):
    image_info = self.images[index]
    image_path = self.images_dir / image_info["file_name"]
    image_tensor = self._load_image_tensor(image_path)
    target = self._load_target(image_info)

    if self.random_hflip > 0 and random.random() < self.random_hflip:
      image_tensor, target = self._horizontal_flip(image_tensor, target)

    return image_tensor, target
