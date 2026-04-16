async function loadMemory() {
  const res = await fetch("https://personal1-e9lq.onrender.com/memory");
  const data = await res.json();

  const tbody = document.querySelector("#memoryTable tbody");
  tbody.innerHTML = "";

  data.memories.forEach(mem => {
    addRow(mem.category, mem.content);
  });
}

function addRow(category = "", content = "") {
  const tbody = document.querySelector("#memoryTable tbody");

  const row = document.createElement("tr");

  row.innerHTML = `
    <td><input value="${category}" placeholder="category"></td>
    <td><textarea rows="2">${content}</textarea></td>
  `;

  tbody.appendChild(row);
}

async function saveAll() {
  const rows = document.querySelectorAll("#memoryTable tbody tr");

  const memories = [];

  rows.forEach(row => {
    const category = row.querySelector("input").value.trim();
    const content = row.querySelector("textarea").value.trim();

    if (category && content) {
      memories.push({ category, content });
    }
  });

  const res = await fetch("https://personal1-e9lq.onrender.com/memory/bulk_update", {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ memories })
  });

  const data = await res.json();

  document.getElementById("status").innerText = "Saved!";
}

loadMemory();
