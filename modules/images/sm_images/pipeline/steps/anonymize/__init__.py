"""The ``anonymize`` built-in step (``[anonymize]`` extra). Importing this
package pulls in neither onnxruntime nor numpy; the detector imports them
on first use."""

from sm_images.pipeline.steps.anonymize.detectors import Detection, Detector, OnnxDetector
from sm_images.pipeline.steps.anonymize.step import (
    AnonymizeParams,
    AnonymizeStep,
    register_anonymize,
)

__all__ = [
    "AnonymizeParams",
    "AnonymizeStep",
    "Detection",
    "Detector",
    "OnnxDetector",
    "register_anonymize",
]
