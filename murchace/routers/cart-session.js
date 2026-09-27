(() => {
  class CartSession extends HTMLElement {
    constructor() {
      super();
    }

    static get observedAttributes() {
      return ["cart"];
    }

    connectedCallback() {
      this.render();
    }

    attributeChangedCallback(name, oldValue, newValue) {
      if (name === "cart" && oldValue !== newValue) {
        this.render();
      }
    }

    getCatalog() {
      try {
        const raw = this.getAttribute("data-catalog");
        return raw ? JSON.parse(raw) : {};
      } catch (e) {
        return {};
      }
    }

    getCart() {
      try {
        const raw = this.getAttribute("cart");
        if (!raw) return [];
        const parsed = JSON.parse(raw);
        return Array.isArray(parsed) ? parsed : [];
      } catch (e) {
        return [];
      }
    }

    render() {
      const cart = this.getCart();
      const catalog = this.getCatalog();

      const totalCount = cart.length;
      let totalPrice = 0;

      // Group items for display or list individual items
      // In murchace, individual items in order of addition are displayed in ul
      const itemElements = cart.map((productId, index) => {
        const product = catalog[productId] || {
          name: `商品 #${productId}`,
          price: 0,
          price_str: "¥0",
        };
        totalPrice += product.price;

        return `
          <li class="flex justify-between items-center py-2 px-4 border-b-4 border-gray-200">
            <div class="overflow-x-auto whitespace-nowrap sm:flex sm:flex-1 sm:justify-between p-2">
              <p class="sm:flex-1 font-medium">${product.name}</p>
              <div>${product.price_str}</div>
            </div>
            <div class="flex items-center ml-2">
              <button
                type="button"
                data-on-click="$cart = $cart.filter((_, i) => i !== ${index})"
                class="font-bold text-white text-2xl bg-red-600 px-2 rounded-sm active:bg-red-700"
              >✕</button>
            </div>
          </li>
        `;
      });

      const formattedTotalPrice = `¥${totalPrice.toLocaleString()}`;
      const isDisabled = totalCount === 0;

      this.innerHTML = `
        <div id="order-session" class="min-h-0 pt-2 flex flex-col h-full justify-between">
          <div class="flex flex-col-reverse overflow-y-auto grow">
            <ul class="text-lg divide-y-4 divide-gray-200">
              ${itemElements.join("")}
            </ul>
          </div>
          <div class="flex flex-row p-2 items-center border-t border-gray-300">
            <div class="basis-1/4 text-right lg:text-2xl">${totalCount} 点</div>
            <div class="basis-2/4 text-center lg:text-2xl">合計: ${formattedTotalPrice}</div>
            <button
              type="button"
              data-on-click="@get('/register/confirm-modal')"
              class="basis-1/4 lg:text-xl text-center text-white p-2 rounded-sm bg-blue-600 active:bg-blue-700 ${
                isDisabled ? "opacity-50 cursor-not-allowed pointer-events-none" : ""
              }"
              ${isDisabled ? "disabled" : ""}
            >確定</button>
            <div id="order-modal-container"></div>
          </div>
        </div>
      `;

      // If Datastar is present, bind newly created elements
      if (window.datastar && typeof window.datastar.apply === "function") {
        window.datastar.apply(this);
      }
    }
  }

  if (!customElements.get("cart-session")) {
    customElements.define("cart-session", CartSession);
  }
})();
