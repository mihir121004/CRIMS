document.querySelectorAll(".counter").forEach(counter => {
    const target = parseInt(counter.textContent.trim());

    if (isNaN(target) || target === 0) {
        return;
    }

    const speed = target / 50;
    let count = 0;

    counter.innerText = "0";

    const update = () => {
        count += speed;
        if (count < target) {
            counter.innerText = Math.floor(count);
            requestAnimationFrame(update);
        } else {
            counter.innerText = target;
        }
    };

    requestAnimationFrame(update);
});