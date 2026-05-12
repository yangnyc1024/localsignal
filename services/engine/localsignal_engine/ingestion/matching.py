from localsignal_engine.models import Place


def matching_places(text: str, places: list[Place]) -> list[Place]:
    normalized = text.lower()
    matches: list[Place] = []

    for place in places:
        names = {place.name.lower()}
        if place.neighborhood:
            names.add(f"{place.name} {place.neighborhood}".lower())
        if any(name in normalized for name in names):
            matches.append(place)

    return matches
