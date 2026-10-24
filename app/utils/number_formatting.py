"""
Number and Currency Formatting Utilities for Bangladeshi / South Asian Standards.

Capabilities:
1. format_quantity:
   - Expands scientific notation (e.g. '3E+4' -> '30,000').
   - Formats whole numbers with thousand separators without trailing zeroes (30000.0 -> '30,000').
   - Preserves meaningful decimal quantities (e.g. 10.5 -> '10.5').

2. format_indian_number / format_money_inr:
   - South Asian / Indian comma grouping: rightmost 3 digits group together,
     then pairs of 2 digits to the left (e.g. 100000 -> '1,00,000.00').
   - Handles negative amounts, decimals, None, and empty inputs.

3. amount_to_words_bangla / amount_in_words:
   - Converts monetary amounts to words using South Asian numbering (Lacs and Crores).
   - Uses popular Bangladeshi terms: Lac, Lacs, Crore, Crores, Taka, Poisha.
   - Example: 100000 -> 'One Lac Taka Only'
   - Example: 1234567.89 -> 'Twelve Lacs Thirty-Four Thousand Five Hundred Sixty-Seven Taka and Eighty-Nine Poisha Only'
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

ONES = [
    "", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
    "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
    "Seventeen", "Eighteen", "Nineteen"
]

TENS = [
    "", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"
]


def format_quantity(val: Any) -> str:
    """
    Format quantity values to human-understandable standard numbers:
    - Eliminates scientific notation (e.g. '3E+4' -> '30,000')
    - Strips unnecessary trailing zeroes (e.g. 10000.0 -> '10,000')
    - Adds thousand separators for readability
    """
    if val is None or val == "":
        return "0"

    try:
        clean_val = str(val).replace(",", "").strip()
        d = Decimal(clean_val)
        # Format as fixed-point without scientific notation
        s = format(d, "f")
        if "." in s:
            s = s.rstrip("0").rstrip(".")
        if not s or s == "-0":
            return "0"

        parts = s.split(".")
        int_part = parts[0]
        is_neg = int_part.startswith("-")
        if is_neg:
            int_part = int_part[1:]

        # Format integer portion with comma separation
        formatted_int = f"{int(int_part):,}" if int_part else "0"
        if is_neg:
            formatted_int = "-" + formatted_int

        if len(parts) > 1 and parts[1]:
            return f"{formatted_int}.{parts[1]}"
        return formatted_int
    except Exception:
        return str(val)


def format_indian_number(val: Any, decimals: int = 2) -> str:
    """
    Format numbers using South Asian / Indian grouping:
    - Rightmost 3 digits group together, then groups of 2 digits (e.g. 1,00,000.00).
    """
    if val is None or val == "":
        return "0.00" if decimals > 0 else "0"

    try:
        clean_val = str(val).replace(",", "").strip()
        d = Decimal(clean_val)
    except Exception:
        return str(val)

    is_negative = d < 0
    d = abs(d)

    s = f"{d:.{decimals}f}" if decimals > 0 else f"{d:.0f}"
    parts = s.split(".")
    int_part = parts[0]
    dec_part = parts[1] if len(parts) > 1 else ""

    if len(int_part) <= 3:
        formatted_int = int_part
    else:
        last3 = int_part[-3:]
        rest = int_part[:-3]
        groups = []
        while len(rest) > 2:
            groups.append(rest[-2:])
            rest = rest[:-2]
        if rest:
            groups.append(rest)
        groups.reverse()
        formatted_int = ",".join(groups) + "," + last3

    if is_negative:
        formatted_int = "-" + formatted_int

    return f"{formatted_int}.{dec_part}" if dec_part else formatted_int


def _under_thousand(n: int) -> str:
    """Convert an integer between 0 and 999 into English words."""
    words = []
    hundreds = n // 100
    remainder = n % 100
    if hundreds > 0:
        words.append(f"{ONES[hundreds]} Hundred")
    if remainder > 0:
        if remainder < 20:
            words.append(ONES[remainder])
        else:
            ten = remainder // 10
            one = remainder % 10
            if one > 0:
                words.append(f"{TENS[ten]}-{ONES[one]}")
            else:
                words.append(TENS[ten])
    return " ".join(words)


def integer_to_bd_words(n: int) -> str:
    """Convert an integer to Bangladeshi words using Crores, Lacs, and Thousands."""
    if n == 0:
        return "Zero"
    if n < 0:
        return "Minus " + integer_to_bd_words(abs(n))

    parts = []

    # 1 Crore = 10,000,000 (100 Lacs)
    # Crores can be arbitrarily large (e.g. 250 Crores)
    crores = n // 10000000
    rem = n % 10000000

    if crores > 0:
        crore_words = integer_to_bd_words(crores)
        unit = "Crore" if crores == 1 else "Crores"
        parts.append(f"{crore_words} {unit}")

    # 1 Lac = 100,000 (100 Thousands)
    lacs = rem // 100000
    rem = rem % 100000
    if lacs > 0:
        lac_words = _under_thousand(lacs)
        unit = "Lac" if lacs == 1 else "Lacs"
        parts.append(f"{lac_words} {unit}")

    thousands = rem // 1000
    rem = rem % 1000
    if thousands > 0:
        thousand_words = _under_thousand(thousands)
        parts.append(f"{thousand_words} Thousand")

    if rem > 0:
        parts.append(_under_thousand(rem))

    return " ".join(parts)


def amount_to_words_bangla(val: Any, currency: str = "Taka") -> str:
    """
    Convert a monetary value to words using popular Bangladeshi terminology:
    Uses 'Lacs' and 'Crores' instead of millions and billions.
    Includes 'Taka' and 'Poisha' sub-units, ending with 'Only'.
    """
    if val is None or val == "":
        return f"Zero {currency} Only"

    try:
        clean_val = str(val).replace(",", "").strip()
        d = Decimal(clean_val).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        return str(val)

    is_negative = d < 0
    d = abs(d)

    taka = int(d)
    poisha = int((d - taka) * 100)

    words = []
    if taka > 0:
        words.append(f"{integer_to_bd_words(taka)} {currency}")
    elif poisha == 0:
        words.append(f"Zero {currency}")

    if poisha > 0:
        poisha_words = _under_thousand(poisha)
        if taka > 0:
            words.append(f"and {poisha_words} Poisha")
        else:
            words.append(f"{poisha_words} Poisha")

    prefix = "Minus " if is_negative else ""
    return prefix + " ".join(words) + " Only"
