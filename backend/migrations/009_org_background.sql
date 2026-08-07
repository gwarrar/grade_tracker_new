-- The page background, per theme.
--
-- Primary and accent were never the whole palette. An institution whose identity is
-- a warm off-white or a true black could restyle every button and heading and still
-- sit on the product's own backdrop, which is the part of a page there is most of.
--
-- The admin picker validates a candidate against the text tokens, which are not
-- configurable, so a background that swallows body copy is refused before it is
-- stored. Hex validity is enforced by `BrandColor.__post_init__`; no CHECK here, for
-- the same reason the four existing colour columns have none.
--
-- The defaults are the shipped `--bg` values in web/app/tokens.css and must stay in
-- step with them: that CSS is what renders in the moment before the branding
-- response arrives, so a mismatch is a visible flash of the wrong colour.
ALTER TABLE organization
    ADD COLUMN color_background_light TEXT NOT NULL DEFAULT '#FBFBFA';

ALTER TABLE organization
    ADD COLUMN color_background_dark TEXT NOT NULL DEFAULT '#08080A';
