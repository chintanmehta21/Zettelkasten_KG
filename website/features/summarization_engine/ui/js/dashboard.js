const form = document.querySelector("#batch-form");
const output = document.querySelector("#output");

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const urls = document.querySelector("#urls").value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  output.textContent = "Running...";
  const response = await fetch("/api/v2/batch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ urls }),
  });
  const data = await response.json();
  output.textContent = JSON.stringify(data, null, 2);
});
