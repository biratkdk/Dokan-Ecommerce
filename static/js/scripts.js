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

window.toggleNavDropdown = function toggleNavDropdown(trigger) {
    const dropdown = trigger.closest("[data-nav-dropdown]");
    if (!dropdown) {
        return;
    }
    const wasOpen = dropdown.classList.contains("is-open");
    document.querySelectorAll("[data-nav-dropdown].is-open").forEach((el) => el.classList.remove("is-open"));
    if (!wasOpen) {
        dropdown.classList.add("is-open");
    }
};

document.addEventListener("click", (event) => {
    document.querySelectorAll("[data-nav-dropdown].is-open").forEach((dropdown) => {
        if (!dropdown.contains(event.target)) {
            dropdown.classList.remove("is-open");
        }
    });
});

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

const sameBillingCheckbox = document.getElementById("id_same_billing_address");
const billingFields = document.getElementById("billing-fields");

function syncBillingFieldsVisibility() {
    if (!sameBillingCheckbox || !billingFields) {
        return;
    }
    billingFields.style.display = sameBillingCheckbox.checked ? "none" : "block";
}

if (sameBillingCheckbox && billingFields) {
    syncBillingFieldsVisibility();
    sameBillingCheckbox.addEventListener("change", syncBillingFieldsVisibility);
}
