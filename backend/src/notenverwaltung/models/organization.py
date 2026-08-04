"""The :class:`Organization` model: branding, locale and grading policy.

One row, edited by an administrator, read by every request. It is what makes the
product configurable without a redeploy — colours, logo, enabled languages, default
theme, and the grading scale that was hardcoded in ``Grade.letter_grade`` before.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from notenverwaltung.exceptions import ValidationError
from notenverwaltung.grading_scale import DEFAULT_SCALE, GradingScale
from notenverwaltung.models.user import Theme

_HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_LOCALE_RE = re.compile(r"^[a-z]{2}(?:-[A-Z]{2})?$")

SUPPORTED_LOCALES = ("en", "de", "fr")
"""Languages with translation files in the repository.

An administrator chooses which of these are offered and which is the default; adding
a fourth means adding ``web/messages/xx.json`` and this tuple. Individual strings can
be overridden per organisation without any code change — see the ``i18n_overrides``
table.
"""


@dataclass
class BrandColor:
    """A brand colour with a variant for each theme.

    Two values rather than one because a colour legible on white is frequently
    illegible on near-black. Storing a single hex and deriving the other at render
    time produces exactly the unreadable combinations the contrast checker exists to
    prevent.

    Attributes:
        light: Hex colour used in light mode.
        dark: Hex colour used in dark mode.
    """

    light: str
    dark: str

    def __post_init__(self) -> None:
        """Validate both variants.

        Raises:
            ValidationError: If either value is not a 3- or 6-digit hex colour.
        """
        for name, value in (("light", self.light), ("dark", self.dark)):
            if not _HEX_COLOR_RE.match(value):
                raise ValidationError(
                    f"{value!r} is not a hex colour.", field=f"color_{name}", value=value
                )


@dataclass
class Organization:
    """Institution-wide configuration.

    Attributes:
        name: Full institution name, shown in the header and on reports.
        short_name: Abbreviation for tight spaces.
        logo_path: Uploaded logo, or ``None`` for the wordmark.
        favicon_path: Uploaded favicon.
        primary: Brand colour for primary actions.
        accent: Brand colour for highlights.
        default_locale: Language for users who have expressed no preference.
        enabled_locales: Languages offered in the switcher.
        default_theme: Colour scheme for users who have expressed no preference.
        timezone: IANA zone used when rendering timestamps.
        grading_scale: The bands that turn a percentage into a letter.
        updated_at: ISO timestamp of the last change.
    """

    name: str
    short_name: str = ""
    logo_path: str | None = field(default=None)
    favicon_path: str | None = field(default=None)
    primary: BrandColor = field(default_factory=lambda: BrandColor("#2E5BFF", "#7C9BFF"))
    accent: BrandColor = field(default_factory=lambda: BrandColor("#00A37A", "#3DD9AC"))
    default_locale: str = "en"
    enabled_locales: tuple[str, ...] = SUPPORTED_LOCALES
    default_theme: Theme = Theme.SYSTEM
    timezone: str = "UTC"
    grading_scale: GradingScale = DEFAULT_SCALE
    updated_at: str | None = field(default=None)

    def __post_init__(self) -> None:
        """Normalise and validate the configuration.

        Raises:
            ValidationError: If the name is blank, a locale is malformed or not
                supported, or the default locale is not among the enabled ones.
        """
        self.name = self.name.strip()
        self.short_name = self.short_name.strip()
        if not self.name:
            raise ValidationError("Organisation name cannot be empty.", field="name")

        if not self.enabled_locales:
            raise ValidationError("At least one locale must be enabled.", field="enabled_locales")

        for locale in self.enabled_locales:
            if not _LOCALE_RE.match(locale):
                raise ValidationError(
                    f"{locale!r} is not a valid locale tag.", field="enabled_locales", value=locale
                )
            if locale not in SUPPORTED_LOCALES:
                raise ValidationError(
                    f"No translation file ships for {locale!r}.",
                    field="enabled_locales",
                    value=locale,
                    supported=list(SUPPORTED_LOCALES),
                )

        # Otherwise a user with no preference would be sent to a language the
        # switcher does not offer, and could not get back.
        if self.default_locale not in self.enabled_locales:
            raise ValidationError(
                f"The default locale {self.default_locale!r} is not enabled.",
                field="default_locale",
                enabled=list(self.enabled_locales),
            )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable representation.

        This is the payload behind ``GET /org/branding``: the frontend injects the
        colours as CSS custom properties, so re-theming needs no rebuild.
        """
        return {
            "name": self.name,
            "short_name": self.short_name,
            "logo_path": self.logo_path,
            "favicon_path": self.favicon_path,
            "colors": {
                "primary": {"light": self.primary.light, "dark": self.primary.dark},
                "accent": {"light": self.accent.light, "dark": self.accent.dark},
            },
            "default_locale": self.default_locale,
            "enabled_locales": list(self.enabled_locales),
            "default_theme": str(self.default_theme),
            "timezone": self.timezone,
            "grading_scale": self.grading_scale.to_list(),
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_row(cls, row: Any) -> Organization:
        """Build an organisation from an ``organization`` table row.

        Args:
            row: A mapping with the table's column names.

        Returns:
            The reconstructed organisation.

        Raises:
            ValidationError: If a stored JSON column is malformed.
        """
        try:
            enabled = tuple(json.loads(row["enabled_locales_json"]))
            scale = GradingScale.from_list(json.loads(row["grading_scale_json"]))
            theme = Theme(row["default_theme"])
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ValidationError(f"Malformed organisation configuration: {exc}") from exc

        return cls(
            name=row["name"],
            short_name=row["short_name"],
            logo_path=row["logo_path"],
            favicon_path=row["favicon_path"],
            primary=BrandColor(row["color_primary_light"], row["color_primary_dark"]),
            accent=BrandColor(row["color_accent_light"], row["color_accent_dark"]),
            default_locale=row["default_locale"],
            enabled_locales=enabled,
            default_theme=theme,
            timezone=row["timezone"],
            grading_scale=scale,
            updated_at=row["updated_at"],
        )
