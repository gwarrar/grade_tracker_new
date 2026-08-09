"""Letter-grade banding.

In the coursework version the A/B/C/D/F thresholds were hardcoded inside
``Grade.letter_grade``. Institutions genuinely differ here — some use A-F at
90/80/70/60, German schools use 1-6, others use pass/merit/distinction — so the
bands live in a value object that an organisation can configure.

:data:`DEFAULT_SCALE` reproduces the thresholds from the project specification, so
``Grade.letter_grade`` behaves exactly as before unless a scale is supplied.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from notenverwaltung.exceptions import ValidationError


@dataclass(frozen=True)
class GradeBand:
    """One band in a grading scale.

    Attributes:
        min_percentage: Inclusive lower bound, as a percentage of the maximum grade.
        label: The label awarded at or above ``min_percentage``, e.g. ``"A"``.
        points: What this band is worth in a grade point average, or ``None`` when
            the institution has not decided. Optional because a GPA only means
            something once somebody says what an A is worth, and defaulting to 4.0
            would assume an American scale in a product that ships in German and
            French. No relationship to ``min_percentage`` is enforced: a German 1-6
            scale awards its *lowest* number to its *highest* threshold, and this
            type has no business having an opinion about that.
    """

    min_percentage: float
    label: str
    points: float | None = None

    def __post_init__(self) -> None:
        """Validate and normalise one displayed grade band.

        Raises:
            ValidationError: If the threshold is outside a finite percentage range,
                the displayed label is blank, or the points are negative.
        """
        if not math.isfinite(self.min_percentage) or not 0 <= self.min_percentage <= 100:
            raise ValidationError(
                "A grading threshold must be a finite percentage from 0 to 100.",
                field="min_percentage",
                value=self.min_percentage,
            )
        label = self.label.strip()
        if not label:
            raise ValidationError("A grading band label cannot be blank.", field="label")
        object.__setattr__(self, "label", label)

        if self.points is not None and (not math.isfinite(self.points) or self.points < 0):
            raise ValidationError(
                "Grade points must be a finite number of zero or more.",
                field="points",
                value=self.points,
            )


@dataclass(frozen=True)
class GradingScale:
    """An ordered set of bands mapping a percentage to a label.

    Bands are stored highest-threshold-first so that lookup is a simple scan.

    Attributes:
        bands: Bands in descending order of ``min_percentage``.
    """

    bands: tuple[GradeBand, ...]

    def __post_init__(self) -> None:
        """Validate the scale.

        Raises:
            ValidationError: If there are no bands, if they are not in descending
                order, or if the lowest band does not reach 0 (which would leave
                some percentages unlabelled).
        """
        if not self.bands:
            raise ValidationError("A grading scale needs at least one band.")

        thresholds = [b.min_percentage for b in self.bands]
        if len(thresholds) != len(set(thresholds)):
            raise ValidationError("Grading scale thresholds must be unique.", thresholds=thresholds)

        if thresholds != sorted(thresholds, reverse=True):
            raise ValidationError(
                "Grading scale bands must be ordered from highest to lowest threshold.",
                thresholds=thresholds,
            )

        if self.bands[-1].min_percentage != 0:
            raise ValidationError(
                "The lowest band must start at 0, otherwise some scores have no label.",
                lowest=self.bands[-1].min_percentage,
            )

    def label_for(self, percentage: float) -> str:
        """Return the label for a percentage score.

        Args:
            percentage: Score as a percentage of the course maximum, 0-100.

        Returns:
            The label of the highest band whose threshold the percentage meets.
        """
        for band in self.bands:
            if percentage >= band.min_percentage:
                return band.label
        # Unreachable: __post_init__ guarantees a band at 0.
        return self.bands[-1].label

    def points_for(self, percentage: float) -> float | None:
        """Return the grade points a percentage earns.

        Args:
            percentage: Score as a percentage of the course maximum, 0-100.

        Returns:
            The points of the band the percentage falls in, or ``None`` when that
            band carries none. A caller averaging these must drop the missing ones
            rather than treat them as zero — an unpriced band is an unanswered
            question, and zero is an answer.
        """
        for band in self.bands:
            if percentage >= band.min_percentage:
                return band.points
        # Unreachable: __post_init__ guarantees a band at 0.
        return self.bands[-1].points

    def to_list(self) -> list[dict[str, object]]:
        """Return a JSON-serialisable representation, for storage in organisation config.

        ``points`` is omitted when unset rather than written as null, so an
        organisation that never configures a GPA sees its stored scale unchanged.
        """
        return [
            {"min_percentage": b.min_percentage, "label": b.label}
            if b.points is None
            else {"min_percentage": b.min_percentage, "label": b.label, "points": b.points}
            for b in self.bands
        ]

    @classmethod
    def from_list(cls, data: list[dict[str, object]]) -> GradingScale:
        """Rebuild a scale from :meth:`to_list` output.

        Args:
            data: Band dictionaries with ``min_percentage`` and ``label`` keys, and
                optionally ``points``. Its absence is not an error: every scale
                stored before grade points existed lacks it, and those must keep
                loading.

        Returns:
            The reconstructed scale.

        Raises:
            ValidationError: If a band is missing a key or has a non-numeric threshold.
        """
        try:
            parsed: list[GradeBand] = []
            for band in data:
                label = band["label"]
                if not isinstance(label, str):
                    raise TypeError("grading band labels must be text")
                points = band.get("points")
                parsed.append(
                    GradeBand(
                        min_percentage=float(band["min_percentage"]),  # type: ignore[arg-type]
                        label=label,
                        points=None if points is None else float(points),  # type: ignore[arg-type]
                    )
                )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError(f"Malformed grading scale: {exc}") from exc
        return cls(bands=tuple(parsed))


DEFAULT_SCALE = GradingScale(
    bands=(
        GradeBand(90.0, "A", 4.0),
        GradeBand(80.0, "B", 3.0),
        GradeBand(70.0, "C", 2.0),
        GradeBand(60.0, "D", 1.0),
        GradeBand(0.0, "F", 0.0),
    )
)
"""The A-F scale from the project specification: A≥90, B≥80, C≥70, D≥60, else F.

Priced 4-3-2-1-0 because this particular scale *is* the American one — carrying its
conventional points is a fact about A-F, not an assumption imposed on anyone. An
institution using its own labels starts with no points and sets them itself.
"""
