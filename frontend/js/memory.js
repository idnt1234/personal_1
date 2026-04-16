async function loadMemory() {
  const res = await fetch("/memory");
  const data = await res.json();

  const tbody = document.querySelector("#memoryTable tbody");
  tbody.innerHTML = "";

  data.memories.forEach(mem => {
    const row = document.createElement("tr");

    row.innerHTML = `
      <td>${mem.category}</td>
      <td>${mem.content}</td>
    `;

    tbody.appendChild(row);
  });
}

loadMemory();
