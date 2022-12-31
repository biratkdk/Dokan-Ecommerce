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

const verificationBanner = document.getElementById("verification-banner");

if (verificationBanner) {
    if (sessionStorage.getItem("verificationBannerDismissed") === "1") {
        verificationBanner.style.display = "none";
    }
}

window.dismissVerificationBanner = function dismissVerificationBanner() {
    if (verificationBanner) {
        verificationBanner.style.display = "none";
    }
    sessionStorage.setItem("verificationBannerDismissed", "1");
};
