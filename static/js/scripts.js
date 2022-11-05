const menuItems = document.getElementById("MenuItems");

if (menuItems) {
    menuItems.style.maxHeight = "0px";
}

window.toggleMenu = function toggleMenu() {
    if (!menuItems) {
        return;
    }

    menuItems.style.maxHeight =
        menuItems.style.maxHeight === "0px" ? "240px" : "0px";
};

window.setTimeout(() => {
    document.querySelectorAll("[data-flash]").forEach((message) => {
        message.classList.add("flash-dismiss");
    });
}, 3500);
