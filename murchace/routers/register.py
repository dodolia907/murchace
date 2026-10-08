from collections.abc import Iterable
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID, uuid4

from datastar_py import attribute_generator as data
from datastar_py.fastapi import DatastarResponse, read_signals
from datastar_py.sse import ServerSentEventGenerator as SSE
from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Request, Response
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
    input,
    li,
    main,
    p,
    span,
    ul,
)

from ..components import clock, page_layout
from ..receipt_service import PrinterQueueDeps, build_receipt_data
from ..store import OrderedItemTable, OrderTable, Product, ProductTable

router = APIRouter()


@dataclass
class OrderSession:
    @dataclass
    class CountedProduct:
        name: str
        price: str
        count: int = 1

    items: dict[UUID, Product]
    counted_products: dict[int, CountedProduct]
    total_count: int = 0
    total_price: int = 0

    def clear(self):
        self.total_count = 0
        self.total_price = 0
        self.items = {}
        self.counted_products = {}

    def total_price_str(self) -> str:
        return Product.to_price_str(self.total_price)

    def add(self, p: Product):
        self.total_count += 1
        self.total_price += p.price
        self.items[uuid4()] = p
        if p.product_id in self.counted_products:
            self.counted_products[p.product_id].count += 1
        else:
            counted_product = self.CountedProduct(name=p.name, price=p.price_str())
            self.counted_products[p.product_id] = counted_product

    def delete(self, item_id: UUID):
        if item_id in self.items:
            self.total_count -= 1
            product = self.items.pop(item_id)
            self.total_price -= product.price
            if self.counted_products[product.product_id].count == 1:
                self.counted_products.pop(product.product_id)
            else:
                self.counted_products[product.product_id].count -= 1


def page_register(req: Request) -> HTMLElement:
    return page_layout(
        req,
        div(data.init("@post('/register')"), id="register", class_="hidden"),
        "新規注文 - murchace",
    )


def register(
    req: Request, products: list[Product], session: OrderSession
) -> HTMLElement:
    inner = div(id="register", class_="h-dvh flex flex-row")[
        main(
            class_="w-1/2 lg:w-4/6 h-full grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 2xl:grid-cols-6 auto-cols-max auto-rows-min gap-2 py-2 pl-10 pr-6 overflow-y-auto"
        )[
            [
                figure(
                    data.on(
                        "click",
                        f"@post('/register/items?product_id={product.product_id}')",
                    ),
                    class_="flex flex-col border-4 border-gray-200 rounded-md transition-colors ease-in-out active:bg-gray-100",
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
                    data.on("click", "@delete('/register/items')"),
                    class_="text-white px-2 py-1 rounded-sm bg-red-600 hidden sm:inline-block",
                    tabindex="0",
                )["全消去"],
                div(class_="text-xl hidden md:inline-block")[clock],
            ],
            order_session(session),
        ],
    ]
    return page_layout(req, inner, "新規注文 - murchace")


def order_session(session: OrderSession) -> Element:
    def item(item_id: UUID, product: Product):
        return li(id=f"item-{item_id}", class_="flex justify-between")[
            div(
                class_="overflow-x-auto whitespace-nowrap sm:flex sm:flex-1 sm:justify-between p-4"
            )[p(class_="sm:flex-1")[product.name], div[product.price_str()]],
            div(class_="flex items-center")[
                button(
                    data.on("click", f"@delete('/register/items/{item_id}')"),
                    class_="font-bold text-white text-2xl bg-red-600 px-2 rounded-sm",
                )["✕"]
            ],
        ]

    return div(id="order-session", class_="min-h-0 pt-2 flex flex-col")[
        # `flex-col-reverse` lets the browser to pin scroll to bottom
        div(class_="flex flex-col-reverse overflow-y-auto")[
            ul(class_="text-lg divide-y-4 divide-gray-200")[
                [item(item_id, product) for item_id, product in session.items.items()]
            ]
        ],
        div(class_="flex flex-row p-2 items-center")[
            div(class_="basis-1/4 text-right lg:text-2xl")[f"{session.total_count} 点"],
            div(class_="basis-2/4 text-center lg:text-2xl")[
                f"合計: {session.total_price_str()}"
            ],
            button(
                data.on("click", "@get('/register/confirm-modal')"),
                class_="basis-1/4 lg:text-xl text-center text-white p-2 rounded-sm bg-blue-600 disabled:cursor-not-allowed disabled:text-gray-700 disabled:bg-gray-100",
                disabled=True if session.total_count == 0 else None,
            )["確定"],
            div(id="order-modal-container"),
        ],
    ]


def confirm_modal(session: OrderSession) -> Element:
    total_price = session.total_price
    signals_init = {
        "received": total_price,
    }
    return div(id="order-modal-container")[
        div(
            id="order-modal",
            class_="z-10 fixed inset-0 w-dvw h-dvh py-4 flex items-center bg-gray-500/75",
            role="dialog",
            aria_modal="true",
            onclick="this.remove()",
        )[
            div(
                data.signals(signals_init),
                id="order-confirm-modal",
                class_="mx-auto w-5/6 md:w-2/3 xl:w-1/3 max-h-[90vh] p-4 flex flex-col gap-y-3 rounded-lg bg-white relative animate-[scale-50_150ms_ease-in] overflow-y-auto",
                onclick="event.stopPropagation()",
            )[
                button(
                    class_="absolute top-0 right-0 px-4 py-3 text-3xl font-bold bg-transparent rounded-tr-lg",
                    onclick="window['order-modal'].remove()",
                )["✕"],
                article(
                    class_="grow min-h-0 flex flex-col gap-y-2 px-3 text-center text-lg"
                )[
                    h2(class_="font-semibold text-xl")["注文の確定"],
                    _total(
                        session.counted_products.values(),
                        session.total_count,
                        session.total_price_str(),
                    ),
                    div(class_="mt-2 pt-2 border-t border-gray-200 flex flex-col gap-y-2 text-base")[
                        div(class_="flex flex-row items-center justify-between font-medium")[
                            span["お預かり金額:"],
                            div(class_="flex items-center gap-x-1")[
                                span["¥"],
                                input(
                                    data.bind("received"),
                                    type="number",
                                    min="0",
                                    step="1",
                                    class_="w-32 px-2 py-1 text-right text-lg font-bold border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500",
                                ),
                            ],
                        ],
                        div(class_="flex flex-wrap gap-1 justify-end")[
                            button(
                                data.on("click", f"$received = {total_price}"),
                                type="button",
                                class_="px-2 py-1 text-sm bg-gray-100 hover:bg-gray-200 border border-gray-300 rounded font-medium cursor-pointer",
                            )["ちょうど"],
                            button(
                                data.on("click", "$received = ($received || 0) + 1000"),
                                type="button",
                                class_="px-2 py-1 text-sm bg-gray-100 hover:bg-gray-200 border border-gray-300 rounded font-medium cursor-pointer",
                            )["+1,000円"],
                            button(
                                data.on("click", "$received = ($received || 0) + 5000"),
                                type="button",
                                class_="px-2 py-1 text-sm bg-gray-100 hover:bg-gray-200 border border-gray-300 rounded font-medium cursor-pointer",
                            )["+5,000円"],
                            button(
                                data.on("click", "$received = ($received || 0) + 10000"),
                                type="button",
                                class_="px-2 py-1 text-sm bg-gray-100 hover:bg-gray-200 border border-gray-300 rounded font-medium cursor-pointer",
                            )["+10,000円"],
                            button(
                                data.on("click", "$received = 0"),
                                type="button",
                                class_="px-2 py-1 text-sm bg-red-50 hover:bg-red-100 text-red-600 border border-red-200 rounded font-medium cursor-pointer",
                            )["クリア"],
                        ],
                        div(class_="flex flex-row items-center justify-between text-lg font-bold pt-1")[
                            span(
                                data.class_(
                                    f"{{'text-red-600': ($received || 0) < {total_price}, 'text-gray-900': ($received || 0) >= {total_price}}}"
                                )
                            )[
                                span(data.show(f"($received || 0) >= {total_price}"))["お釣り:"],
                                span(data.show(f"($received || 0) < {total_price}"))["不足:"],
                            ],
                            span(
                                data.class_(
                                    f"{{'text-red-600': ($received || 0) < {total_price}, 'text-green-700': ($received || 0) >= {total_price}}}"
                                )
                            )[
                                span(
                                    data.show(f"($received || 0) >= {total_price}"),
                                    data.text(f"'¥' + Math.max(0, ($received || 0) - {total_price}).toLocaleString()"),
                                )["¥0"],
                                span(
                                    data.show(f"($received || 0) < {total_price}"),
                                    data.text(f"'¥' + Math.max(0, {total_price} - ($received || 0)).toLocaleString()"),
                                )["¥0"],
                            ],
                        ],
                    ],
                ],
                button(
                    data.on("click", "@post('/register')"),
                    data.attr({"disabled": f"($received || 0) < {total_price}"}),
                    class_="w-full py-4 text-center text-xl font-semibold text-white bg-blue-600 rounded-sm disabled:opacity-50 disabled:cursor-not-allowed",
                )["確認"],
            ]
        ]
    ]


def issued_modal(
    order_id: int,
    session: OrderSession,
    received: int | None = None,
    change: int | None = None,
) -> Element:
    return div(id="order-modal-container")[
        div(
            id="order-modal",
            class_="z-10 fixed inset-0 w-dvw h-dvh py-4 flex items-center bg-gray-500/75",
            role="dialog",
            aria_modal="true",
        )[
            div(
                class_="mx-auto w-5/6 md:w-2/3 xl:w-1/3 max-h-[90vh] p-4 flex flex-col gap-y-2 rounded-lg bg-white animate-[scale-95_150ms_ease-in] overflow-y-auto"
            )[
                article(
                    class_="grow min-h-0 flex flex-col gap-y-2 px-3 text-center text-lg"
                )[
                    h2(class_="font-semibold text-xl")[f"注文番号 #{order_id}"],
                    _total(
                        session.counted_products.values(),
                        session.total_count,
                        session.total_price_str(),
                        received=received,
                        change=change,
                    ),
                ],
                button(
                    data.on("click", "@post('/register')"),
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
    counted_products: Iterable[OrderSession.CountedProduct],
    total_count: int,
    total_price: str,
    received: int | None = None,
    change: int | None = None,
) -> list[Element]:
    elements = [
        ul(class_="grow flex flex-col overflow-y-auto max-h-48")[
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
        div(class_="border-t border-gray-200 pt-2")[
            p(class_="flex flex-row")[
                span["計"],
                span(class_="ml-auto whitespace-nowrap")[f"{total_count} 点"],
            ],
            p(class_="flex flex-row font-semibold")[
                span(class_="break-words")["合計金額"],
                span(class_="ml-auto")[total_price],
            ],
        ],
    ]
    if received is not None:
        elements.append(
            div(class_="border-t border-gray-200 pt-1 text-base")[
                p(class_="flex flex-row text-gray-700")[
                    span["お預かり"],
                    span(class_="ml-auto")[Product.to_price_str(received)],
                ],
                p(class_="flex flex-row font-bold text-gray-900")[
                    span["お釣り"],
                    span(class_="ml-auto")[Product.to_price_str(change if change is not None else 0)],
                ],
            ]
        )
    return elements


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


# NOTE: Do NOT store this data in database because the data is transient and should be kept in memory
order_sessions: dict[UUID, OrderSession] = {}
SESSION_COOKIE_KEY = "session_key"


async def order_session_dep(session_key: Annotated[UUID, Cookie()]) -> OrderSession:
    if (order_session := order_sessions.get(session_key)) is None:
        raise HTTPException(status_code=404, detail=f"Session {session_key} not found")
    return order_session


SessionDeps = Annotated[OrderSession, Depends(order_session_dep)]


@router.get("/register", response_class=HTMLResponse)
async def instruct_creation_of_new_session_or_get_existing_session(
    request: Request,
    session_key: Annotated[UUID | None, Cookie()] = None,
    c: Annotated[list[int] | None, Query()] = None,  # category
):
    if session_key is None or (session := order_sessions.get(session_key)) is None:
        return HTMLResponse(page_register(request))

    products = await (
        ProductTable.by_category_ids(c) if c is not None else ProductTable.select_all()
    )
    return HTMLResponse(register(request, products, session))


@router.get("/register/confirm-modal")
async def get_confirm_dialog(session: SessionDeps):
    if session.total_count == 0:
        fragment = error_modal("商品が選択されていません")
    else:
        fragment = confirm_modal(session)
    return DatastarResponse(SSE.patch_elements(fragment))


@router.post("/register")
async def create_new_session_or_place_order(
    request: Request,
    queue: PrinterQueueDeps,
    session_key: Annotated[UUID | None, Cookie()] = None,
):
    if session_key is None or (session := order_sessions.get(session_key)) is None:
        session_key = _create_new_session()

        res = DatastarResponse(SSE.execute_script("location.reload()"))
        res.headers["location"] = "/register"
        res.set_cookie(SESSION_COOKIE_KEY, str(session_key))
        return res

    if session.total_count == 0:
        fragment = error_modal("商品が選択されていません")
        return DatastarResponse(SSE.patch_elements(fragment))

    received: int | None = None
    signals = await read_signals(request)
    if signals and "received" in signals:
        try:
            val = int(signals["received"])
            if val >= 0:
                received = val
        except (ValueError, TypeError):
            pass

    order_sessions.pop(session_key)
    res = await _place_order(session, queue, received=received)
    res.delete_cookie(SESSION_COOKIE_KEY)
    return res


def _create_new_session() -> UUID:
    session_key = uuid4()
    order_sessions[session_key] = OrderSession(items={}, counted_products={})
    return session_key


async def _place_order(
    session: SessionDeps,
    queue: PrinterQueueDeps,
    received: int | None = None,
) -> Response:
    product_ids = [item.product_id for item in session.items.values()]
    order_id = await OrderedItemTable.issue(product_ids)
    # TODO: add a branch for out of stock error
    ordered_at = await OrderTable.insert(order_id)

    received_str = Product.to_price_str(received) if received is not None else None
    change = max(0, received - session.total_price) if received is not None else None
    change_str = Product.to_price_str(change) if change is not None else None

    # Enqueue receipt for printing (ordered_at from DB ensures accurate timestamp)
    queue.enqueue(
        build_receipt_data(
            order_id,
            session,
            ordered_at=ordered_at,
            received_str=received_str,
            change_str=change_str,
        )
    )

    fragment = issued_modal(order_id, session, received=received, change=change)
    return DatastarResponse(SSE.patch_elements(fragment))


@router.post("/register/items")
async def add_session_item(session: SessionDeps, product_id: int) -> Response:
    if (product := await ProductTable.by_product_id(product_id)) is None:
        raise HTTPException(status_code=404, detail=f"Product {product_id} not found")

    session.add(product)
    fragment = order_session(session)
    return DatastarResponse(SSE.patch_elements(fragment))


@router.delete("/register/items/{item_id}")
async def delete_session_item(session: SessionDeps, item_id: UUID):
    session.delete(item_id)
    fragment = order_session(session)
    return DatastarResponse(SSE.patch_elements(fragment))


@router.delete("/register/items")
async def clear_session_items(session: SessionDeps) -> Response:
    session.clear()
    fragment = order_session(session)
    return DatastarResponse(SSE.patch_elements(fragment))


# TODO: add proper path operation for order deferral
# # TODO: Store this data in database
# deferred_order_sessions: dict[int, OrderSession] = {}
#
#
# @router.post("/register/deferred")
# async def post_defer_session(request: Request, session_key: Annotated[UUID, Cookie()]):
#     order_session = await order_session_dep(session_key)
#     if order_session in deferred_order_sessions:
#         raise HTTPException(
#             status_code=status.HTTP_409_CONFLICT,
#             detail=f"Deferred session already exists",
#         )
#     deferred_order_sessions.append(order_sessions.pop(session_key))
#     # TODO: respond with a message about the success of the deferral action
#     # message = "注文を保留しました"
#     # res = HTMLResponse(
#     #     tmp_session(request, OrderSession(), message=message)
#     # )
#     # res.delete_cookie(SESSION_COOKIE_KEY)
#     # return res
