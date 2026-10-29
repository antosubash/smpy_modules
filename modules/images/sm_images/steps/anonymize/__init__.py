"""The ``anonymize`` built-in step (``[anonymize]`` extra). Importing this
package pulls in neither torch nor ultralytics; the detector imports them on
first use."""

from sm_images.steps.anonymize.detectors import Detection, Detector, YoloDetector
from sm_images.steps.anonymize.step import AnonymizeParams, AnonymizeStep, register_anonymize

__all__ = [
    "AnonymizeParams",
    "AnonymizeStep",
    "Detection",
    "Detector",
    "YoloDetector",
    "register_anonymize",
]
