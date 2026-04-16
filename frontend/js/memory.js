async function saveMemory() {
  const category = document.getElementById("category").value;
  const content = document.getElementById("content").value;

  const res = await fetch("/memory/update", {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      category,
      content
    })
  });

  const data = await res.json();

  document.getElementById("status").innerText = "✅ saved";
}
