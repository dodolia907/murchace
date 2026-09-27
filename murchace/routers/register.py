import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from datastar_py import attribute_generator as data
from datastar_py.fastapi import DatastarResponse, read_signals
from datastar_py.sse import ServerSentEventGenerator as SSE
from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse
from htpy import (
    Element,
    HTMLElement,
    a,
    article,
    aside,
    button,
    div,
    figcaption,
    figure,
    h2,
    img,
    li,
    main,
    p,
    script,
    span,
    ul,
)
from markupsafe import Markup

from ..components import clock, page_layout
from ..store import OrderedItemTable, OrderTable, Product, ProductTable

router = APIRouter()

with open(Path(__file__).parent / "cart-session.js", encoding="utf-8") as f:
    _cart_session_script = script[Markup(f.read())]


@dataclass
class CartSummary:
    @dataclass
    class CountedProduct:
        name: str
        price: str
        count: int = 1

    counted_products: dict[int, CountedProduct]
    total_count: int = 0
    total_price: int = 0

    def total_price_str(self) -> str:
        return Product.to_price_str(self.total_price)

    @classmethod
    async def from_product_ids(cls, product_ids: list[int]) -> "CartSummary":
        summary = cls(counted_products={})
        product_cache: dict[int, Product | None] = {}
        for pid in product_ids:
            if pid not in product_cache:
                product_cache[pid] = await ProductTable.by_product_id(pid)
            if (product := product_cache[pid]) is not None:
                summary.total_count += 1
                summary.total_price += product.price
                if pid in summary.counted_products:
                    summary.counted_products[pid].count += 1
                else:
                    summary.counted_products[pid] = cls.CountedProduct(
                        name=product.name, price=product.price_str()
                    )
        return summary


def register(req: Request, products: list[Product]) -> HTMLElement:
    # Catalog of product metadata for client-side rendering
    catalog = {
        p.product_id: {
            "name": p.name,
            "price": p.price,
            "price_str": p.price_str(),
        }
        for p in products
    }
    catalog_json = json.dumps(catalog)

    inner = div(
        data.signals({"cart": []}).ifmissing,
        {"data-persist": "cart"},
        id="register",
        class_="h-dvh flex flex-row",
    )[
        main(
            class_="w-1/2 lg:w-4/6 h-full grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 2xl:grid-cols-6 auto-cols-max auto-rows-min gap-2 py-2 pl-10 pr-6 overflow-y-auto"
        )[
            [
                figure(
                    data.on("click", f"$cart = [...$cart, {product.product_id}]"),
                    class_="flex flex-col border-4 border-gray-200 rounded-md transition-colors ease-in-out active:bg-gray-100 cursor-pointer",
                )[
                    img(
                        class_="mx-auto w-full h-auto aspect-square",
                        src=str(req.url_for("static", path=product.filename)),
                        alt=product.name,
                    ),
                    figcaption(class_="text-center truncate")[product.name],
                    div(class_="text-center")[product.price_str()],
                ]
                for product in products
            ]
        ],
        aside(class_="w-1/2 lg:w-2/6 h-full flex flex-col p-4 justify-between")[
            div(class_="flex flex-row py-2 justify-around items-center text-xl")[
                a(
                    href="/",
                    class_="px-2 py-1 rounded-sm bg-gray-300 hidden lg:inline-block",
                )["ホーム"],
                button(
                    data.on("click", "$cart = []"),
                    class_="text-white px-2 py-1 rounded-sm bg-red-600 hidden sm:inline-block",
                    tabindex="0",
                )["全消去"],
                div(class_="text-xl hidden md:inline-block")[clock],
            ],
            Element("cart-session")(
                data.attr({"cart": "JSON.stringify($cart)"}),
                data_catalog=catalog_json,
            ),
        ],
        _cart_session_script,
    ]
    return page_layout(req, inner, "新規注文 - murchace")


def confirm_modal(summary: CartSummary) -> Element:
    return div(id="order-modal-container")[
        div(
            id="order-modal",
            class_="z-10 fixed inset-0 w-dvw h-dvh py-4 flex items-center bg-gray-500/75",
            role="dialog",
            aria_modal="true",
            onclick="this.remove()",
        )[
            div(
                id="order-confirm-modal",
                class_="mx-auto w-5/6 md:w-2/3 xl:w-1/3 h-4/5 p-4 flex flex-col gap-y-2 rounded-lg bg-white relative animate-[scale-50_150ms_ease-in]",
                onclick="event.stopPropagation()",
            )[
                button(
                    class_="absolute top-0 right-0 px-4 py-3 text-3xl font-bold bg-transparent rounded-tr-lg",
                    onclick="window['order-modal'].remove()",
                )["✕"],
                article(
                    class_="grow min-h-0 flex flex-col gap-y-2 px-3 text-center text-lg"
                )[
                    h2(class_="font-semibold")["注文の確定"],
                    _total(
                        summary.counted_products.values(),
                        summary.total_count,
                        summary.total_price_str(),
                    ),
                ],
                button(
                    data.on("click", "@post('/register')"),
                    class_="w-full py-4 text-center text-xl font-semibold text-white bg-blue-600 rounded-sm",
                )["確認"],
            ]
        ]
    ]


def issued_modal(order_id: int, summary: CartSummary) -> Element:
    return div(id="order-modal-container")[
        div(
            id="order-modal",
            class_="z-10 fixed inset-0 w-dvw h-dvh py-4 flex items-center bg-gray-500/75",
            role="dialog",
            aria_modal="true",
        )[
            div(
                class_="mx-auto w-5/6 md:w-2/3 xl:w-1/3 h-4/5 p-4 flex flex-col gap-y-2 rounded-lg bg-white animate-[scale-95_150ms_ease-in]"
            )[
                article(
                    class_="grow min-h-0 flex flex-col gap-y-2 px-3 text-center text-lg"
                )[
                    h2(class_="font-semibold")[f"注文番号 #{order_id}"],
                    _total(
                        summary.counted_products.values(),
                        summary.total_count,
                        summary.total_price_str(),
                    ),
                ],
                button(
                    data.on("click", "window['order-modal'].remove()"),
                    class_="w-full py-4 text-center text-xl font-semibold text-white bg-green-600 rounded-sm",
                )["新規"],
                a(
                    href="/",
                    class_="w-full py-4 text-center text-xl font-semibold bg-white border border-gray-300 rounded-sm",
                )["ホームに戻る"],
            ]
        ]
    ]


def _total(
    counted_products: Iterable[CartSummary.CountedProduct],
    total_count: int,
    total_price: str,
) -> list[Element]:
    return [
        ul(class_="grow flex flex-col overflow-y-auto")[
            (
                li(class_="flex flex-row items-start gap-x-2")[
                    span(class_="break-words")[counted_product.name],
                    span(class_="ml-auto whitespace-nowrap")[
                        f"{counted_product.price} x {counted_product.count}"
                    ],
                ]
                for counted_product in counted_products
            )
        ],
        div[
            p(class_="flex flex-row")[
                span["計"],
                span(class_="ml-auto whitespace-nowrap")[f"{total_count} 点"],
            ],
            p(class_="flex flex-row")[
                span(class_="break-words")["合計金額"],
                span(class_="ml-auto")[total_price],
            ],
        ],
    ]


def error_modal(message: str) -> Element:
    return div(id="order-modal-container")[
        div(
            id="order-modal",
            class_="z-10 fixed inset-0 w-dvw h-dvh py-4 flex items-center bg-gray-500/75",
            role="dialog",
            aria_modal="true",
        )[
            div(
                id="order-error-modal",
                class_="mx-auto w-5/6 md:w-2/3 xl:w-1/3 h-4/5 p-4 flex flex-col gap-y-2 rounded-lg bg-white [.datastar-settling_&]:scale-50 transition-transform duration-150",
            )[
                article(
                    class_="grow min-h-0 flex flex-col gap-y-2 px-3 text-center text-lg"
                )[h2(class_="font-semibold text-red-500")["エラー"], p[message]],
                button(
                    class_="w-full py-4 text-center text-xl font-semibold bg-white border border-gray-300 rounded-sm",
                    onclick="window['order-modal'].remove()",
                )["閉じる"],
            ]
        ]
    ]


async def extract_cart_product_ids(request: Request) -> list[int]:
    signals = await read_signals(request)
    if not signals or "cart" not in signals:
        return []
    cart_raw = signals["cart"]
    if not isinstance(cart_raw, list):
        return []
    product_ids: list[int] = []
    for item in cart_raw:
        try:
            product_ids.append(int(item))
        except (ValueError, TypeError):
            continue
    return product_ids


@router.get("/register", response_class=HTMLResponse)
async def get_register_page(
    request: Request,
    c: Annotated[list[int] | None, Query()] = None,  # category
):
    products = await (
        ProductTable.by_category_ids(c) if c is not None else ProductTable.select_all()
    )
    return HTMLResponse(register(request, products))


@router.get("/register/confirm-modal")
async def get_confirm_dialog(request: Request):
    product_ids = await extract_cart_product_ids(request)
    if not product_ids:
        fragment = error_modal("商品が選択されていません")
    else:
        summary = await CartSummary.from_product_ids(product_ids)
        fragment = confirm_modal(summary)
    return DatastarResponse(SSE.patch_elements(fragment))


@router.post("/register")
async def place_order(request: Request) -> Response:
    product_ids = await extract_cart_product_ids(request)
    if not product_ids:
        fragment = error_modal("商品が選択されていません")
        return DatastarResponse(SSE.patch_elements(fragment))

    # Verify products exist
    for pid in product_ids:
        if (await ProductTable.by_product_id(pid)) is None:
            raise HTTPException(status_code=404, detail=f"Product {pid} not found")

    order_id = await OrderedItemTable.issue(product_ids)
    await OrderTable.insert(order_id)

    summary = await CartSummary.from_product_ids(product_ids)
    fragment = issued_modal(order_id, summary)

    # Clear cart signal on the client and display modal
    return DatastarResponse(
        [SSE.patch_elements(fragment), SSE.patch_signals({"cart": []})]
    )
