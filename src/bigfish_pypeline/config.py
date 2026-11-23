"""Configuration file: settings, defaults, checks, YAML reading and writing.

The layout and defaults follow section 6.2 of the specification. A settings file
is read with `load_config` and written with `save_config`. Problems in a file are
collected in one `ConfigError`, with one plain-English message for each.
"""

import difflib
import os
import types
from pathlib import Path
from typing import Annotated, Any, Literal, Union, get_args, get_origin

import yaml
from annotated_types import Ge, Gt, Le
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    PrivateAttr,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticCustomError

CONFIG_VERSION = 1

# Lab OMERO server, used when a config does not name another one.
OMERO_HOST = "10.34.168.89"
OMERO_PORT = 4064

AXES_CHOICES = ("ZCYX", "CZYX", "ZYX", "CYX", "YX")


class ConfigError(Exception):
    """A settings file or a command-line value has problems.

    `messages` lists every problem in plain English, each naming the setting.
    """

    def __init__(self, messages):
        if isinstance(messages, str):
            messages = [messages]
        self.messages = list(messages)
        super().__init__(str(self))

    def __str__(self):
        if len(self.messages) == 1:
            return self.messages[0]
        return "\n".join(f"- {message}" for message in self.messages)


# ---------------------------------------------------------------------------
# Building blocks for the settings
# ---------------------------------------------------------------------------


def _blank_to_none(value):
    """An empty value in the file (nothing after the colon, or "") means "not set"."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return value


def _blank_to_text(value):
    return "" if value is None else value


def _whole_if_possible(value):
    """Write numbers such as 5.0 as 5 in saved files."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


_tidy = PlainSerializer(_whole_if_possible, return_type=Union[int, float])

Number = Annotated[float, _tidy]
PositiveNumber = Annotated[float, Gt(0), _tidy]
NonNegativeNumber = Annotated[float, Ge(0), _tidy]
Fraction = Annotated[float, Gt(0), Le(1), _tidy]
NonNegativeInt = Annotated[int, Ge(0)]
PositiveInt = Annotated[int, Ge(1)]
Text = Annotated[str, BeforeValidator(_blank_to_text)]

OptionalNumber = Annotated[Number | None, BeforeValidator(_blank_to_none)]
OptionalPositiveNumber = Annotated[PositiveNumber | None, BeforeValidator(_blank_to_none)]
OptionalPositiveInt = Annotated[PositiveInt | None, BeforeValidator(_blank_to_none)]


def _rule_error(*problems):
    """Report problems found by a rule that looks at several settings.

    Each problem is (setting, text): the setting, written relative to the group
    being checked, and the rest of the sentence.
    """
    return PydanticCustomError("config_rule", "A setting breaks a rule.", {"problems": list(problems)})


def _check_workers(value):
    if value == "auto":
        return value
    if isinstance(value, int) and not isinstance(value, bool) and value >= 1:
        return value
    raise _rule_error(("", "must be `auto` or a whole number of 1 or more"))


Workers = Annotated[Any, BeforeValidator(_check_workers)]


class _Settings(BaseModel):
    """Base of every group of settings: no unknown names, no loose type conversion."""

    model_config = ConfigDict(strict=True, extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _blank_group_means_defaults(cls, data):
        return {} if data is None else data


# ---------------------------------------------------------------------------
# Groups of settings, in the order of the file
# ---------------------------------------------------------------------------


class OmeroSettings(_Settings):
    host: Text = OMERO_HOST
    port: Annotated[int, Ge(1), Le(65535)] = OMERO_PORT
    username: Text = ""
    dataset_id: OptionalPositiveInt = None
    image_ids: list[PositiveInt] = Field(default_factory=list)


class InputSettings(_Settings):
    source: Literal["local", "omero"] = "local"
    folder: Text = ""
    filter: Text = ""
    extension: Literal[".tif", ".tiff"] = ".tif"
    omero: OmeroSettings = Field(default_factory=OmeroSettings)


class RunSettings(_Settings):
    name: Text = "my_run"
    input: InputSettings = Field(default_factory=InputSettings)
    output_folder: Text = ""
    workers: Workers = "auto"
    keep_awake: bool = True
    seed: NonNegativeInt = 0


class VoxelSize(_Settings):
    z: OptionalPositiveNumber = None
    yx: PositiveNumber


class ImageSettings(_Settings):
    axes: Literal["ZCYX", "CZYX", "ZYX", "CYX", "YX"]
    voxel_size_nm: VoxelSize

    @model_validator(mode="after")
    def _z_matches_axes(self):
        has_z = "Z" in self.axes
        z = self.voxel_size_nm.z
        if has_z and z is None:
            raise _rule_error(("voxel_size_nm.z", f"is needed for the 3D layout `{self.axes}`"))
        if not has_z and z is not None:
            raise _rule_error(
                ("voxel_size_nm.z", f"must be left empty for the 2D layout `{self.axes}`")
            )
        return self


class MicroscopeSettings(_Settings):
    type: Literal["confocal", "widefield", "nipkow"] = "confocal"
    NA: PositiveNumber = 1.45
    RI: PositiveNumber = 1.45


class BackgroundSettings(_Settings):
    method: Literal["rolling_ball", "tophat"] = "rolling_ball"
    radius_px: PositiveNumber = 5


class ThresholdSettings(_Settings):
    mode: Literal["manual", "auto", "calibrated"] = "auto"
    value: OptionalNumber = None
    lower_limit: OptionalNumber = None
    calibration_filter: Text = ""

    @model_validator(mode="after")
    def _mode_needs(self):
        if self.mode == "manual" and self.value is None:
            raise _rule_error(("value", "is needed when `mode` is `manual`: the threshold to use"))
        if self.mode == "calibrated" and not self.calibration_filter.strip():
            raise _rule_error(
                (
                    "calibration_filter",
                    "is needed when `mode` is `calibrated`: text that the names of the "
                    "calibration images contain",
                )
            )
        return self


class BailoutSettings(_Settings):
    enabled: bool = False
    max_spots: OptionalPositiveInt = None

    @model_validator(mode="after")
    def _enabled_needs_limit(self):
        if self.enabled and self.max_spots is None:
            raise _rule_error(("max_spots", "is needed when `bailout.enabled` is true"))
        return self


class DecompositionSettings(_Settings):
    enabled: bool = True
    alpha: NonNegativeNumber = 0.5
    beta: NonNegativeNumber = 1


class SubpixelSettings(_Settings):
    enabled: bool = False


class ClusterSettings(_Settings):
    enabled: bool = True
    radius_nm: PositiveInt = 500
    min_spots: PositiveInt = 4


class MeasurementSettings(_Settings):
    snr: bool = False
    intensity: bool = False


class ChannelSettings(_Settings):
    index: NonNegativeInt
    name: Text = ""
    ex: PositiveNumber = 570
    em: PositiveNumber = 610
    background: BackgroundSettings = Field(default_factory=BackgroundSettings)
    threshold: ThresholdSettings = Field(default_factory=ThresholdSettings)
    bailout: BailoutSettings = Field(default_factory=BailoutSettings)
    decomposition: DecompositionSettings = Field(default_factory=DecompositionSettings)
    subpixel: SubpixelSettings = Field(default_factory=SubpixelSettings)
    clusters: ClusterSettings = Field(default_factory=ClusterSettings)
    measurements: MeasurementSettings = Field(default_factory=MeasurementSettings)


class ClipSettings(_Settings):
    enabled: bool = False
    value: PositiveNumber = 100


class SegmentationBackgroundSettings(_Settings):
    enabled: bool = True
    method: Literal["rolling_ball", "tophat"] = "rolling_ball"
    radius_px: PositiveNumber = 200


class CellposeSettings(_Settings):
    model: Text = "cpsam_v2"
    diameter: OptionalPositiveNumber = None
    flow_threshold: NonNegativeNumber = 0.4
    cellprob_threshold: Number = 0
    min_size: int = 15
    max_size_fraction: Fraction = 0.4
    normalize: bool = True
    batch_size: PositiveInt = 1
    niter: OptionalPositiveInt = None


class SegmentationSettings(_Settings):
    enabled: bool = False
    source: Literal["cellpose", "label_files"] = "cellpose"
    label_folder: Text = ""
    channel: NonNegativeInt = 0
    projection: Literal["max", "mean"] = "max"
    clip: ClipSettings = Field(default_factory=ClipSettings)
    background: SegmentationBackgroundSettings = Field(
        default_factory=SegmentationBackgroundSettings
    )
    median_px: OptionalPositiveInt = None
    gaussian_sigma_px: OptionalPositiveNumber = None
    cellpose: CellposeSettings = Field(default_factory=CellposeSettings)
    device: Literal["auto", "cuda", "mps", "cpu"] = "auto"
    drop_border_cells: bool = False

    @model_validator(mode="after")
    def _label_files_need_folder(self):
        if self.enabled and self.source == "label_files" and not self.label_folder.strip():
            raise _rule_error(("label_folder", "is needed when `source` is `label_files`"))
        return self


class QcSettings(_Settings):
    elbow_plot: bool = True
    detection: bool = True
    reference_spot: bool = True
    cellpose: bool = True
    final: Literal["png", "html", "none"] = "png"


class OutputSettings(_Settings):
    label_images: bool = True
    npz: bool = False
    qc: QcSettings = Field(default_factory=QcSettings)


class ResolvedSettings(_Settings):
    """What a run worked out for itself, written by the pipeline.

    `images` lists the images that were processed: file names for local input,
    text naming each image for OMERO input. `thresholds` holds one calibrated
    threshold for each channel index that used the `calibrated` mode.
    """

    images: list[Text] = Field(default_factory=list)
    thresholds: dict[NonNegativeInt, Number] = Field(default_factory=dict)


class Config(_Settings):
    """All settings of a run."""

    config_version: int
    run: RunSettings = Field(default_factory=RunSettings)
    image: ImageSettings
    microscope: MicroscopeSettings = Field(default_factory=MicroscopeSettings)
    channels: list[ChannelSettings] = Field(min_length=1)
    segmentation: SegmentationSettings = Field(default_factory=SegmentationSettings)
    outputs: OutputSettings = Field(default_factory=OutputSettings)
    resolved: ResolvedSettings | None = None

    # Folder of the file this config was read from; relative folders start here.
    _config_folder: Path | None = PrivateAttr(default=None)

    @model_validator(mode="before")
    @classmethod
    def _image_group_may_be_missing(cls, data):
        # A missing `image` group is reported setting by setting.
        if isinstance(data, dict) and data.get("image") is None:
            data = {**data, "image": {}}
        return data

    @field_validator("config_version", mode="before")
    @classmethod
    def _version_is_known(cls, value):
        if isinstance(value, int) and not isinstance(value, bool) and value == CONFIG_VERSION:
            return value
        if value is None:
            found = ""
        elif isinstance(value, str):
            found = " (it is written as text; remove the quotes)"
        else:
            found = f" (this file says {_show(value)})"
        raise _rule_error(("", f"must be {CONFIG_VERSION}{found}"))

    @model_validator(mode="after")
    def _channels_are_distinct(self):
        problems = []
        first_seen = {}
        for position, channel in enumerate(self.channels):
            if channel.index in first_seen:
                problems.append(
                    (
                        f"channels[{position}].index",
                        f"repeats channel {channel.index}, already used by "
                        f"`channels[{first_seen[channel.index]}].index`",
                    )
                )
            else:
                first_seen[channel.index] = position
        if self.resolved is not None:
            for index in self.resolved.thresholds:
                if index not in first_seen:
                    problems.append(
                        (
                            f"resolved.thresholds.{index}",
                            f"is for channel {index}, which is not in `channels`",
                        )
                    )
        if problems:
            raise _rule_error(*problems)
        return self

    def __eq__(self, other):
        # Two configs are equal when their settings are; the file they came from does not count.
        if not isinstance(other, Config):
            return NotImplemented
        return self.to_dict() == other.to_dict()

    # -- folders ------------------------------------------------------------

    @property
    def config_folder(self):
        """Folder of the file this config was read from, or None."""
        return self._config_folder

    def with_config_folder(self, folder):
        """Copy of this config that resolves relative folders against `folder`."""
        copy = self.model_copy(deep=True)
        copy._config_folder = None if folder is None else Path(os.path.abspath(folder))
        return copy

    def full_path(self, folder):
        """Full path of a folder setting, or None when it is empty.

        Relative folders start at the config file's folder, or at the current
        folder when the config was not read from a file.
        """
        if not folder or not folder.strip():
            return None
        path = Path(folder).expanduser()
        if not path.is_absolute():
            start = self._config_folder if self._config_folder is not None else Path.cwd()
            path = start / path
        return Path(os.path.abspath(path))

    def full_input_folder(self):
        return self.full_path(self.run.input.folder)

    def full_output_folder(self):
        """Full path of the output folder; None when empty (the pipeline then picks one)."""
        return self.full_path(self.run.output_folder)

    def full_label_folder(self):
        return self.full_path(self.segmentation.label_folder)

    def with_full_paths(self):
        """Copy with every folder written as a full path, as saved in `run_config.yaml`.

        Empty folders stay empty.
        """
        data = self.to_dict()
        for group, name, path in (
            (data["run"]["input"], "folder", self.full_input_folder()),
            (data["run"], "output_folder", self.full_output_folder()),
            (data["segmentation"], "label_folder", self.full_label_folder()),
        ):
            group[name] = "" if path is None else str(path)
        return parse_config(data, self._config_folder)

    # -- other helpers --------------------------------------------------------

    def to_dict(self):
        """Settings as plain Python values, in the order of the file."""
        data = self.model_dump()
        if data["resolved"] is None:
            del data["resolved"]
        return data

    def with_resolved(self, images, thresholds=None):
        """Copy with the `resolved` block filled in.

        `thresholds` maps channel index to the calibrated threshold.
        """
        data = self.to_dict()
        data["resolved"] = {"images": list(images), "thresholds": dict(thresholds or {})}
        return parse_config(data, self._config_folder)

    def without_resolved(self):
        """Copy with the `resolved` block removed."""
        data = self.to_dict()
        data.pop("resolved", None)
        return parse_config(data, self._config_folder)


# ---------------------------------------------------------------------------
# Turning problems into plain messages
# ---------------------------------------------------------------------------


def _show(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _path_text(loc):
    text = ""
    for position, part in enumerate(loc):
        # Numbers in a list are written [0]; channel numbers under `thresholds` are keys.
        if isinstance(part, int) and not (position and loc[position - 1] == "thresholds"):
            text += f"[{part}]"
        else:
            text += ("." if text else "") + str(part)
    return text


def _unwrap(annotation, metadata=()):
    """Strip `Annotated` and `X | None` from a type, collecting the constraints."""
    metadata = list(metadata)
    while True:
        origin = get_origin(annotation)
        if origin is Annotated:
            args = get_args(annotation)
            annotation = args[0]
            metadata.extend(args[1:])
        elif origin in (Union, types.UnionType):
            rest = [arg for arg in get_args(annotation) if arg is not type(None)]
            if len(rest) != 1:
                break
            annotation = rest[0]
        else:
            break
    return annotation, metadata


def _setting_at(loc):
    """Type and constraints of the setting at `loc`, or (None, []) when unknown."""
    annotation, metadata = Config, []
    for part in loc:
        annotation, metadata = _unwrap(annotation, metadata)
        origin = get_origin(annotation)
        if origin is list and isinstance(part, int):
            annotation, metadata = get_args(annotation)[0], []
        elif origin is dict:
            annotation, metadata = get_args(annotation)[1], []
        elif (
            isinstance(annotation, type)
            and issubclass(annotation, BaseModel)
            and part in annotation.model_fields
        ):
            field = annotation.model_fields[part]
            annotation, metadata = field.annotation, field.metadata
        else:
            return None, []
    return _unwrap(annotation, metadata)


def _quoted_choices(choices):
    names = [f"`{choice}`" for choice in choices]
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " or " + names[-1]


def _describe(annotation, metadata):
    """What a setting must be, as the end of a sentence ("a positive number")."""
    origin = get_origin(annotation)
    if origin is Literal:
        return "one of " + _quoted_choices(get_args(annotation))
    if annotation is bool:
        return "true or false"
    if annotation is str:
        return "text"
    if annotation in (int, float):
        bounds = {}
        for item in metadata:
            for name in ("gt", "ge", "lt", "le"):
                if hasattr(item, name):
                    bounds[name] = getattr(item, name)
        word = "whole number" if annotation is int else "number"
        high = bounds.get("le")
        if bounds.get("gt") == 0 and high is not None:
            return f"a {word} above 0 and up to {high}"
        if bounds.get("gt") == 0:
            return f"a positive {word}"
        low = bounds.get("ge")
        if low is not None and high is not None:
            return f"a {word} from {low} to {high}"
        if low is not None:
            return f"a {word} of {low} or more"
        return f"a {word}"
    if origin is list:
        return "a list"
    if origin is dict:
        return "a group of `channel number: value` lines"
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return "a group of settings"
    return None


def _close_name(name, valid_names):
    """The valid name closest to `name`, ignoring capitals, or None."""
    by_lower = {valid.lower(): valid for valid in valid_names}
    close = difflib.get_close_matches(name.lower(), list(by_lower), n=1, cutoff=0.6)
    return by_lower[close[0]] if close else None


def _join(path, relative):
    if not relative:
        return path
    return f"{path}.{relative}" if path else relative


def _messages_for(error):
    """Plain messages for one problem reported by pydantic."""
    loc = tuple(error["loc"])
    kind = error["type"]
    value = error.get("input")

    if kind == "config_rule":
        base = _path_text(loc)
        return [
            f"`{_join(base, setting)}` {text}."
            for setting, text in error["ctx"]["problems"]
        ]

    if "[key]" in loc:
        path = _path_text([part for part in loc if part != "[key]"])
        return [f"`{path}` is not a channel number; use whole numbers of 0 or more."]

    path = _path_text(loc)

    if kind == "extra_forbidden":
        annotation, _ = _setting_at(loc[:-1])
        names = []
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            names = list(annotation.model_fields)
        close = _close_name(str(loc[-1]), names)
        if close:
            return [f"`{path}` is not a known setting – did you mean `{close}`?"]
        return [f"`{path}` is not a known setting."]

    annotation, metadata = _setting_at(loc)
    needs = _describe(annotation, metadata)

    if kind == "too_short" and path == "channels":
        return ["`channels` needs at least one channel."]
    if kind == "too_short":
        return [f"`{path}` needs at least {error['ctx']['min_length']} item(s)."]

    if kind == "missing" or value is None or (isinstance(value, str) and not value.strip()):
        if path == "image.voxel_size_nm":
            return ["`image.voxel_size_nm` is required: `yx`, and `z` for a 3D layout."]
        if path == "config_version":
            return [f"`config_version` is required; write `config_version: {CONFIG_VERSION}`."]
        if path == "channels":
            return ["`channels` needs at least one channel."]
        if needs and annotation is not bool and not needs.startswith("a group"):
            return [f"`{path}` is required; it must be {needs}."]
        return [f"`{path}` is required."]

    if needs is None:
        return [f"`{path}` has a value that is not valid."]

    text = f"`{path}` must be {needs}"
    if isinstance(value, (str, int, float)):
        text += f" (found `{_show(value)}`"
        if isinstance(value, bool) and annotation is not bool:
            text += "; YAML reads yes and on as true, and no and off as false"
        text += ")"
    return [text + "."]


def _messages_from(validation_error):
    messages = []
    for error in validation_error.errors():
        for message in _messages_for(error):
            if message not in messages:
                messages.append(message)
    return messages


# ---------------------------------------------------------------------------
# Reading, writing and changing configs
# ---------------------------------------------------------------------------


def parse_config(data, config_folder=None):
    """Check a dictionary of settings and return a `Config`.

    Raises `ConfigError` listing every problem.
    """
    if not isinstance(data, dict):
        raise ConfigError("The settings must be written as `name: value` lines.")
    try:
        config = Config.model_validate(data)
    except ValidationError as error:
        raise ConfigError(_messages_from(error)) from None
    return config.with_config_folder(config_folder) if config_folder is not None else config


def load_config(path):
    """Read and check a settings file; relative folders start at the file's folder."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        raise ConfigError(f"The settings file `{path}` was not found.") from None
    except (OSError, UnicodeDecodeError) as error:
        raise ConfigError(f"The settings file `{path}` could not be read: {error}") from None
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        problem = getattr(error, "problem", None) or "the text is not valid YAML"
        where = f" near line {mark.line + 1}" if mark is not None else ""
        raise ConfigError(f"`{path.name}` is not a valid settings file{where}: {problem}.") from None
    if not isinstance(data, dict):
        raise ConfigError(
            f"`{path.name}` must hold settings written as `name: value` lines, "
            "as in the example settings file."
        )
    return parse_config(data, Path(os.path.abspath(path)).parent)


class _SettingsDumper(yaml.SafeDumper):
    """Writes empty settings as nothing after the colon, as in the example files."""


_SettingsDumper.add_representer(
    type(None), lambda dumper, _: dumper.represent_scalar("tag:yaml.org,2002:null", "")
)


def save_config(config, path):
    """Write a config as YAML, keeping the order of the settings layout.

    Folders are written as they are stored in the config.
    """
    path = Path(path)
    text = yaml.dump(
        config.to_dict(),
        Dumper=_SettingsDumper,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _command_line_folder(folder):
    """Folders given on the command line start at the current folder."""
    text = str(folder)
    if not text.strip():
        return ""
    return os.path.abspath(Path(text).expanduser())


def _whole_number(value):
    if isinstance(value, str) and value.strip().isdigit():
        return int(value)
    return value


def apply_overrides(
    config,
    *,
    input_folder=None,
    filter=None,
    output_folder=None,
    workers=None,
    dataset_id=None,
    image_ids=None,
):
    """Put values given on the command line or the Batch page on top of a config.

    Values left as None are not changed. A new input folder, filter, dataset ID or
    list of image IDs means other images, so the `resolved` block is dropped; a new
    output folder or number of workers keeps it. Giving a dataset ID replaces any
    image IDs, and the other way round. Returns a new config.
    """
    data = config.to_dict()
    run = data["run"]
    omero = run["input"]["omero"]
    other_images = False

    if input_folder is not None:
        run["input"]["folder"] = _command_line_folder(input_folder)
        other_images = True
    if filter is not None:
        run["input"]["filter"] = filter
        other_images = True
    if dataset_id is not None:
        omero["dataset_id"] = _whole_number(dataset_id)
        omero["image_ids"] = []
        other_images = True
    if image_ids is not None:
        omero["image_ids"] = [_whole_number(value) for value in image_ids]
        omero["dataset_id"] = None
        other_images = True
    if output_folder is not None:
        run["output_folder"] = _command_line_folder(output_folder)
    if workers is not None:
        run["workers"] = _whole_number(workers)
    if other_images:
        data.pop("resolved", None)

    return parse_config(data, config.config_folder)
