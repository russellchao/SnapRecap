/*
    Team brand colors for the recap page.

    Each recap section paints itself from the `--rc-home` / `--rc-away` custom
    properties declared in components/RecapSection.css. `teamPalette()` returns an
    override for those tokens, built from the two teams actually playing, so the
    ledger bars and signal chips read in each team's own colors.

    Two problems have to be solved before a brand color can be used as-is:

      1. The recap surfaces are near-black, so a dark primary (Bears navy, Ravens
         purple, Raiders black) would disappear against them. Colors are lifted in
         lightness — hue and saturation untouched — until they clear a contrast
         threshold against the panel.
      2. Plenty of matchups pair two teams on the same hue (KC vs SF, both red).
         When that happens one side falls back to its secondary color, so the
         "home" and "away" halves of a ledger row never blur together.
*/

// Brand colors as [primary, secondary], keyed by nflverse abbreviation (the form
// the recap route carries — see TEAM_ABBR in pages/Games.jsx). For the teams whose
// official primary is black, the signature color is listed first instead: lifting
// black for legibility only ever yields gray, which identifies no one.
export const TEAM_COLORS = {
    ARI: ["#97233F", "#FFB612"],
    ATL: ["#A71930", "#A5ACAF"],
    BAL: ["#241773", "#9E7C0C"],
    BUF: ["#00338D", "#C60C30"],
    CAR: ["#0085CA", "#BFC0BF"],
    CHI: ["#0B162A", "#C83803"],
    CIN: ["#FB4F14", "#FFFFFF"],
    CLE: ["#FF3C00", "#311D00"],
    DAL: ["#003594", "#869397"],
    DEN: ["#FB4F14", "#002244"],
    DET: ["#0076B6", "#B0B7BC"],
    GB: ["#203731", "#FFB612"],
    HOU: ["#03202F", "#A71930"],
    IND: ["#002C5F", "#A2AAAD"],
    JAX: ["#006778", "#D7A22A"],
    KC: ["#E31837", "#FFB81C"],
    LA: ["#003594", "#FFA300"],
    LAC: ["#0080C6", "#FFC20E"],
    LV: ["#A5ACAF", "#C4C9CC"],
    MIA: ["#008E97", "#FC4C02"],
    MIN: ["#4F2683", "#FFC62F"],
    NE: ["#002244", "#C60C30"],
    NO: ["#D3BC8D", "#A28D5B"],
    NYG: ["#0B2265", "#A71930"],
    NYJ: ["#125740", "#FFFFFF"],
    PHI: ["#004C54", "#A5ACAF"],
    PIT: ["#FFB612", "#A5ACAF"],
    SEA: ["#69BE28", "#002244"],
    SF: ["#AA0000", "#B3995D"],
    TB: ["#D50A0A", "#3d3b3a"],
    TEN: ["#4B92DB", "#0C2340"],
    WAS: ["#5A1414", "#FFB612"],
};

// The darkest point of a section's background gradient (see RecapSection.css) —
// what a team color has to stay legible against.
const SURFACE = "#0f1117";

// 4.5:1 is the WCAG AA floor for normal text, and these colors do carry text
// (chip values, team tags), not just bars.
const MIN_CONTRAST = 4.5;

// Lifting past this reads as pastel rather than as the team's color.
const MAX_LIGHTNESS = 0.82;

// Two colors within this many degrees of hue are treated as the same color at a
// glance, which is all the distinction the page needs them to survive.
const HUE_TOLERANCE = 30;

// Below this saturation a color has no usable hue, so it's compared as a gray.
const GRAY_SATURATION = 0.15;

// A dark, muted color (Packers green) goes gray-green rather than green when it's
// only lifted, so hued colors get this much saturation on the way up.
const MIN_LIFTED_SATURATION = 0.35;

// Fallbacks for an abbreviation with no entry above — the page's original
// lime/orange pairing, so an unmapped team still renders in something.
const DEFAULT_HOME = ["#C7FF3D", "#8ED10A"];
const DEFAULT_AWAY = ["#FF8A3D", "#E0620C"];

function hexToRgb(hex) {
    const value = hex.replace('#', '');
    const full = value.length === 3 ? value.split('').map((c) => c + c).join('') : value;
    const n = parseInt(full, 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function rgbToHex([r, g, b]) {
    const channel = (c) => Math.round(Math.min(Math.max(c, 0), 255)).toString(16).padStart(2, '0');
    return `#${channel(r)}${channel(g)}${channel(b)}`;
}

// WCAG relative luminance, the basis of the contrast ratio below.
function luminance(rgb) {
    const [r, g, b] = rgb.map((c) => {
        const s = c / 255;
        return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(hexA, hexB) {
    const a = luminance(hexToRgb(hexA));
    const b = luminance(hexToRgb(hexB));
    const [light, dark] = a > b ? [a, b] : [b, a];
    return (light + 0.05) / (dark + 0.05);
}

function rgbToHsl([r, g, b]) {
    const [rn, gn, bn] = [r / 255, g / 255, b / 255];
    const max = Math.max(rn, gn, bn);
    const min = Math.min(rn, gn, bn);
    const l = (max + min) / 2;
    const delta = max - min;
    if (delta === 0) return { h: 0, s: 0, l };

    const s = delta / (1 - Math.abs(2 * l - 1));
    let h;
    if (max === rn) h = ((gn - bn) / delta) % 6;
    else if (max === gn) h = (bn - rn) / delta + 2;
    else h = (rn - gn) / delta + 4;
    return { h: (h * 60 + 360) % 360, s, l };
}

function hslToRgb({ h, s, l }) {
    const c = (1 - Math.abs(2 * l - 1)) * s;
    const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
    const m = l - c / 2;
    const sector = Math.floor(h / 60) % 6;
    const [r, g, b] = [
        [c, x, 0], [x, c, 0], [0, c, x], [0, x, c], [x, 0, c], [c, 0, x],
    ][sector];
    return [(r + m) * 255, (g + m) * 255, (b + m) * 255];
}

// Blend toward another color; `amount` is how much of `other` ends up in the result.
function mix(hex, other, amount) {
    const a = hexToRgb(hex);
    const b = hexToRgb(other);
    return rgbToHex(a.map((channel, i) => channel + (b[i] - channel) * amount));
}

/*
    Raise a brand color's lightness until it clears MIN_CONTRAST against the
    section surface, leaving hue and saturation alone so it still reads as the
    team's color. Colors that already pass come back untouched.
*/
function legible(hex) {
    if (contrast(hex, SURFACE) >= MIN_CONTRAST) return hex;

    const { h, s, l: start } = rgbToHsl(hexToRgb(hex));
    // Grays have no hue worth protecting — saturating one would invent a color.
    const saturation = s < GRAY_SATURATION ? s : Math.max(s, MIN_LIFTED_SATURATION);

    for (let l = start; l <= MAX_LIGHTNESS; l += 0.02) {
        const candidate = rgbToHex(hslToRgb({ h, s: saturation, l }));
        if (contrast(candidate, SURFACE) >= MIN_CONTRAST) return candidate;
    }
    return rgbToHex(hslToRgb({ h, s: saturation, l: MAX_LIGHTNESS }));
}

// Would these two read as the same color side by side? Grays have no meaningful
// hue, so they're separated by lightness instead.
function tooSimilar(hexA, hexB) {
    const a = rgbToHsl(hexToRgb(hexA));
    const b = rgbToHsl(hexToRgb(hexB));

    const grayA = a.s < GRAY_SATURATION;
    const grayB = b.s < GRAY_SATURATION;
    if (grayA !== grayB) return false;
    if (grayA && grayB) return Math.abs(a.l - b.l) < 0.25;

    const spread = Math.abs(a.h - b.h);
    return Math.min(spread, 360 - spread) < HUE_TOLERANCE;
}

/*
    Pick the color each team wears on the recap page.

    Both start on their primary. If those clash, the home team switches to its
    secondary; if that clashes too, the away team tries its own secondary. Should
    every combination clash (two teams with near-identical palettes), the primaries
    stand — the section still reads, just with less separation than usual.
*/
function resolvePair(awayColors, homeColors) {
    const away = legible(awayColors[0]);
    const home = legible(homeColors[0]);
    if (!tooSimilar(away, home)) return { away, home };

    const homeAlt = legible(homeColors[1]);
    if (!tooSimilar(away, homeAlt)) return { away, home: homeAlt };

    const awayAlt = legible(awayColors[1]);
    if (!tooSimilar(awayAlt, home)) return { away: awayAlt, home };

    return { away, home };
}

/*
    The `--rc-*` overrides for one matchup, ready to hand to a recap section as an
    inline `style` — inline so it outranks the defaults RecapSection.css sets on
    `.recap-section` itself.

    The `-dim` tokens are the same color pulled most of the way back toward the
    surface, for borders that should hint at the team color without competing with
    the text inside them.
*/
export function teamPalette(awayAbbr, homeAbbr) {
    const { away, home } = resolvePair(
        TEAM_COLORS[awayAbbr] ?? DEFAULT_AWAY,
        TEAM_COLORS[homeAbbr] ?? DEFAULT_HOME,
    );

    return {
        '--rc-away': away,
        '--rc-away-dim': mix(away, SURFACE, 0.6),
        '--rc-home': home,
        '--rc-home-dim': mix(home, SURFACE, 0.6),
    };
}
