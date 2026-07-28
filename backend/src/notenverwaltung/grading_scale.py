"""Letter-grade banding.

In the coursework version the A/B/C/D/F thresholds were hardcoded inside
``Grade.letter_grade``. Institutions genuinely differ here — some use A-F at
90/80/70/60, German schools use 1-6, others use pass/merit/distinction — so the
bands live in a value object that an organisation can configure.

:data:`DEFAULT_SCALE` reproduces the thresholds from the project specification, so
``Grade.letter_grade`` behaves exactly as before unless a scale is supplied.
"""

from __future__ import annotations

from dataclasses import dataclass

from notenverwaltung.exceptions import ValidationError


@dataclass(frozen=True)
class GradeBand:
    """One band in a grading scale.

    Attributes:
        min_percentage: Inclusive lower bound, as a percentage of the maximum grade.
        label: The label awarded at or above ``min_percentage``, e.g. ``"A"``.
    """

    min_percentage: float
    label: str


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
        if thresholds != sorted(thresholds, reverse=True):
            raise ValidationError(
                "Grading scale bands must be ordered from highest to lowest threshold.",
                thresholds=thresholds,
            )

        if self.bands[-1].min_percentage > 0:
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

    def to_list(self) -> list[dict[str, object]]:
        """Return a JSON-serialisable representation, for storage in organisation config."""
        return [{"min_percentage": b.min_percentage, "label": b.label} for b in self.bands]

    @classmethod
    def from_list(cls, data: list[dict[str, object]]) -> GradingScale:
        """Rebuild a scale from :meth:`to_list` output.

        Args:
            data: Band dictionaries with ``min_percentage`` and ``label`` keys.

        Returns:
            The reconstructed scale.

        Raises:
            ValidationError: If a band is missing a key or has a non-numeric threshold.
        """
        try:
            bands = tuple(
                GradeBand(min_percentage=float(b["min_percentage"]), label=str(b["label"]))  # type: ignore[arg-type]
                for b in data
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError(f"Malformed grading scale: {exc}") from exc
        return cls(bands=bands)


DEFAULT_SCALE = GradingScale(
    bands=(
        GradeBand(90.0, "A"),
        GradeBand(80.0, "B"),
        GradeBand(70.0, "C"),
        GradeBand(60.0, "D"),
        GradeBand(0.0, "F"),
    )
)
"""The A-F scale from the project specification: A≥90, B≥80, C≥70, D≥60, else F."""
