import io
import sys
import urllib.request
import zipfile

from load import DATA

FRENCH = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/{}_CSV.zip"
FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={}"
FRENCH_SETS = (
    "F-F_Research_Data_Factors",
    "F-F_Research_Data_Factors_daily",
    "F-F_Momentum_Factor",
    "F-F_Research_Data_5_Factors_2x3",
    "Portfolios_Formed_on_ME",
    "Portfolios_Formed_on_BE-ME",
    "10_Portfolios_Prior_12_2",
    "6_Portfolios_2x3",
    "12_Industry_Portfolios",
    "30_Industry_Portfolios",
    "49_Industry_Portfolios",
    "12_Industry_Portfolios_daily",
    "Portfolios_Formed_on_OP",
    "Portfolios_Formed_on_VAR",
    "Portfolios_Formed_on_D-P",
    "Developed_ex_US_3_Factors",
)
FRED_SETS = ("GS10", "TB3MS", "CPIAUCSL")


def get(url):
    with urllib.request.urlopen(url, timeout=60) as r:  # noqa: S310
        return r.read()


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    for name in FRENCH_SETS:
        with zipfile.ZipFile(io.BytesIO(get(FRENCH.format(name)))) as z:
            for member in z.namelist():
                target = name if name.endswith("_daily") and name.startswith("12_") else member.rsplit(".", 1)[0]
                (DATA / f"{target}.csv").write_bytes(z.read(member))
    for name in FRED_SETS:
        (DATA / f"{name}.csv").write_bytes(get(FRED.format(name)))
    print("fetched into", DATA, file=sys.stderr)


if __name__ == "__main__":
    main()
