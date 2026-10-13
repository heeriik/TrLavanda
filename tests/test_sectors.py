from trlavanda.factors.sectors import sic_to_sector


def test_sic_to_sector_examples():
    assert sic_to_sector(3674) == "Information Technology"  # semiconductores
    assert sic_to_sector(2834) == "Health Care"  # farmacéuticas
    assert sic_to_sector(6021) == "Financials"  # bancos
    assert sic_to_sector(6798) == "Real Estate"  # REIT
    assert sic_to_sector(1311) == "Energy"
    assert sic_to_sector(4922) == "Energy"
    assert sic_to_sector(None) == "Unknown"
