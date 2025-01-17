# Copyright 2022 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import dataclasses
from functools import lru_cache
import json
from nanoemoji.config import FontConfig
from pathlib import Path
from picosvg.svg import SVG
from picosvg.svg_reuse import normalize
from picosvg.svg_types import SVGPath, SVGShape
from typing import Iterable, List, MutableMapping, NewType, Set, Tuple, Union


PathSource = Union[SVGShape, Iterable[SVGShape], "ReuseableParts"]


@lru_cache(maxsize=1)
def _default_tolerence() -> float:
    return FontConfig().reuse_tolerance


def _is_iterable_of(thing, desired_type) -> bool:
    try:
        it = iter(thing)
    except TypeError:
        return False

    try:
        val = next(it)
        return isinstance(val, desired_type)
    except StopIteration:
        return True


# an SVG style path, e.g. the d attribute of <svg:path/>
Shape = NewType("Shape", str)


# A normalized SVG style path
NormalizedShape = NewType("NormalizedShape", str)


# A set of shapes that normalize to the same path
ShapeSet = NewType("ShapeSet", Set[Shape])


@dataclasses.dataclass
class ReuseableParts:
    version: Tuple[int, int, int] = (1, 0, 0)
    reuse_tolerance: float = dataclasses.field(default_factory=_default_tolerence)
    shape_sets: MutableMapping[NormalizedShape, ShapeSet] = dataclasses.field(
        default_factory=dict
    )

    def _add_norm_path(self, norm: NormalizedShape, shape: Shape):
        if norm not in self.shape_sets:
            self.shape_sets[norm] = ShapeSet(set())
        self.shape_sets[norm].add(shape)

    def _add(self, shape: Shape):
        norm = NormalizedShape(shape)
        if self.reuse_tolerance != -1:
            norm = NormalizedShape(normalize(SVGPath(d=shape), self.reuse_tolerance).d)
        self._add_norm_path(norm, shape)

    def add(self, source: PathSource):
        if isinstance(source, ReuseableParts):
            for normalized, shape_set in source.shape_sets.items():
                for shape in shape_set:
                    self._add_norm_path(normalized, shape)
        else:
            if not _is_iterable_of(source, SVGShape):
                source = (source,)
            for a_source in source:
                if not isinstance(a_source, SVGShape):
                    raise ValueError(f"Illegal source {type(a_source)}")
                svg_shape: SVGShape = a_source  # pytype: disable=attribute-error
                self._add(Shape(svg_shape.as_path().d))

    def to_json(self):
        json_dict = {
            "version": ".".join(str(v) for v in self.version),
            "reuse_tolerance": self.reuse_tolerance,
            "shape_sets": [
                {"normalized": n, "shapes": list(s)} for n, s in self.shape_sets.items()
            ],
        }
        return json.dumps(json_dict, indent=2)

    @classmethod
    def fromstring(cls, string) -> "ReuseableParts":
        first = string.strip()[0]
        parts = cls()
        if first == "<":
            svg = SVG.fromstring(string).topicosvg()
            for shape in svg.shapes():
                parts.add(SVGPath(d=shape.as_path().d))
        elif first == "{":
            json_dict = json.loads(string)
            parts.version = tuple(int(v) for v in json_dict.pop("version").split("."))
            assert parts.version == (1, 0, 0), f"Bad version {parts.version}"
            parts.reuse_tolerance = float(json_dict.pop("reuse_tolerance"))
            for shape_set_json in json_dict.pop("shape_sets"):
                norm = NormalizedShape(shape_set_json.pop("normalized"))
                shapes = ShapeSet({Shape(s) for s in shape_set_json.pop("shapes")})
                if shape_set_json:
                    raise ValueError(f"Unconsumed input {shape_set_json}")
                parts.shape_sets[norm] = shapes
            if json_dict:
                raise ValueError(f"Unconsumed input {json_dict}")

        else:
            raise ValueError(f"Unrecognized start sequence {string[:16]}")
        return parts

    @classmethod
    def load(cls, input_file: Path) -> "ReuseableParts":
        ext = input_file.suffix.lower()
        if ext not in {".svg", ".json"}:
            raise ValueError(f"Unknown format {input_file}")
        return cls.fromstring(input_file.read_text(encoding="utf-8"))
