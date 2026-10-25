"""Technology classes (CPC subclasses) and their friendly names.

The ten below seed the demo sample; any other subclass is labelled from the CPC
description on the patent record.
"""

TECH_CLASSES = {
    "A61B": "Medical diagnosis and surgery",
    "A61K": "Drugs and therapeutic preparations",
    "G02B": "Optics and photonics",
    "H01M": "Batteries and fuel cells",
    "H04W": "Wireless networks",
    "G06F": "Computing and software",
    "A01N": "Crop protection and biocides",
    "F03D": "Wind energy",
    "B33Y": "3D printing",
    "C02F": "Water treatment",
}


def label(cpc_subclass: str | None, descriptions: dict | None = None) -> str:
    if not cpc_subclass:
        return "Unclassified"
    code = cpc_subclass[:4]
    if code in TECH_CLASSES:
        return TECH_CLASSES[code]
    desc = (descriptions or {}).get(code, "")
    if desc:
        desc = desc.split(";")[0].strip().capitalize()
        return desc if len(desc) <= 48 else desc[:45].rsplit(" ", 1)[0] + "..."
    return code
