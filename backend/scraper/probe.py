import httpx

API_URL = "https://pcandparts.com/wp-json/wc/store/v1/products"
PARAMS = {"per_page": 20, "page": 1}
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


def probe():
    print(f"Probing: {API_URL}")
    try:
        response = httpx.get(API_URL, params=PARAMS, headers=HEADERS, timeout=15)
    except httpx.TimeoutException:
        print("ERROR: Request timed out after 15s")
        return
    except httpx.ConnectError as e:
        print(f"ERROR: Connection failed — {e}")
        return

    print(f"Status code : {response.status_code}")
    print(f"Content-Type: {response.headers.get('content-type', 'N/A')}")

    if response.status_code != 200 or "json" not in response.headers.get("content-type", ""):
        print(
            f"Store API not open — fall back to HTML scraping "
            f"(status {response.status_code})"
        )
        return

    products = response.json()
    print(f"\nProducts returned: {len(products)}\n")

    for p in products:
        prices = p.get("prices", {})
        print(
            f"  name     : {p.get('name')}\n"
            f"  sku      : {p.get('sku') or 'N/A'}\n"
            f"  price    : {prices.get('price') or 'Request Price'}\n"
            f"  currency : {prices.get('currency_code', 'N/A')}\n"
            f"  in_stock : {p.get('is_in_stock', False)}\n"
        )


if __name__ == "__main__":
    probe()
