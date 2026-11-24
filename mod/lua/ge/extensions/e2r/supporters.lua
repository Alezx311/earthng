-- The people who support EarthNG, as each asked to be named. The generator sets them on the wall
-- of supporters (generator.lua BLD.supportersWall): a board that stands on the proving ground's
-- thanks tile (earthng/proving_thanks.py) and wherever a map has a billboard tagged
-- operator = "EarthNG supporters".
--
-- To add a name: a line in `names`, then rebuild the planet (Rebuild.bat). The board lays its
-- columns out by the count and grows with the list; the pack is not rebuilt. Letters outside the
-- glyph atlas (fast_style.GLYPHS: Latin, Ukrainian and Russian letters, digits, / - . , ' ( ))
-- are set as spaces.
return {
  title = 'EARTHNG SUPPORTERS',
  thanks = 'THANK YOU    ДЯКУЄМО',
  names = {
    'Adrian Burke',
    'Demon Abis',
    'Tyler Reid',
    'Nathan Prince',
    'Benjamin Gratton',
    'Demetrius Piera',
    'SeriousSpy',
    'RC',
  },
}
