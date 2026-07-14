from pathlib import Path

import torch


def require_torchvision():
  try:
    import torchvision  # noqa: F401
    from torchvision.models import ResNet50_Weights  # noqa: F401
    from torchvision.models.detection import maskrcnn_resnet50_fpn_v2  # noqa: F401
    from torchvision.models.detection.faster_rcnn import FastRCNNPredictor  # noqa: F401
    from torchvision.models.detection.mask_rcnn import MaskRCNNPredictor  # noqa: F401
  except Exception as exc:
    raise RuntimeError(
      "torchvision est requis pour la segmentation d'instances. "
      "Installe une version compatible avec torch, par exemple via `pip install torchvision`."
    ) from exc


def build_maskrcnn_model(num_classes, pretrained_backbone=True):
  require_torchvision()
  from torchvision.models import ResNet50_Weights
  from torchvision.models.detection import maskrcnn_resnet50_fpn_v2
  from torchvision.models.detection.faster_rcnn import FastRCNNPredictor
  from torchvision.models.detection.mask_rcnn import MaskRCNNPredictor

  weights_backbone = ResNet50_Weights.DEFAULT if pretrained_backbone else None
  model = maskrcnn_resnet50_fpn_v2(weights=None, weights_backbone=weights_backbone)

  box_in_features = model.roi_heads.box_predictor.cls_score.in_features
  model.roi_heads.box_predictor = FastRCNNPredictor(box_in_features, num_classes)

  mask_in_channels = model.roi_heads.mask_predictor.conv5_mask.in_channels
  model.roi_heads.mask_predictor = MaskRCNNPredictor(mask_in_channels, 256, num_classes)
  return model


def save_checkpoint(output_path, model, categories, config, epoch=None, metrics=None):
  output_path = Path(output_path)
  output_path.parent.mkdir(parents=True, exist_ok=True)
  torch.save(
    {
      "model_state": model.state_dict(),
      "categories": categories,
      "config": config,
      "epoch": epoch,
      "metrics": metrics or {},
    },
    output_path,
  )


def load_model_from_checkpoint(checkpoint_path, device=None):
  checkpoint_path = Path(checkpoint_path)
  device = device or torch.device("cpu")
  checkpoint = torch.load(checkpoint_path, map_location=device, weights_only=False)
  categories = checkpoint.get("categories") or []
  num_classes = len(categories) + 1
  model = build_maskrcnn_model(num_classes=num_classes, pretrained_backbone=False)
  model.load_state_dict(checkpoint["model_state"])
  model.to(device)
  model.eval()
  return model, categories, checkpoint

