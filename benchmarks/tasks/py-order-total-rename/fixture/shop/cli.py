"""``python -m shop.cli 250x2 100 --discount 10`` prints the order total."""
import sys

from shop import pricing


def parse_line(token):
    price, _, qty = token.partition("x")
    return {"price_cents": int(price), "qty": int(qty or 1)}


def main(argv):
    discount = 0
    if "--discount" in argv:
        i = argv.index("--discount")
        discount = int(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    lines = [parse_line(t) for t in argv]
    total = pricing.calc(lines, discount)
    return "%d.%02d" % divmod(total, 100)


if __name__ == "__main__":
    print(main(sys.argv[1:]))
