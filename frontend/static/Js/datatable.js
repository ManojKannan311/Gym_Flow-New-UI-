$(document).ready(function () {
    
    // Auto-fill branch filter options from table column 3
    let branches = new Set();
  
    $("#membersTable tbody tr").each(function () {
      let branch = $(this).find("td:eq(3)").text().trim();
      if (branch) branches.add(branch);
    });
  
    branches = Array.from(branches).sort();
    branches.forEach(function (b) {
      $("#branchFilter").append(`<option value="${b}">${b}</option>`);
    });
  
    function filterTable() {
      let search = $("#searchInput").val().toLowerCase().trim();
      let branch = $("#branchFilter").val();
      let status = $("#statusFilter").val();
  
      $("#membersTable tbody tr").each(function () {
        let name = $(this).find("td:eq(1)").text().toLowerCase();
        let phone = $(this).find("td:eq(2)").text().toLowerCase();
        let rowBranch = $(this).find("td:eq(3)").text().trim();
        let rowStatus = $(this).find("td:eq(7)").text().trim(); // badge text
  
        let matchSearch = !search || name.includes(search) || phone.includes(search);
        let matchBranch = !branch || rowBranch === branch;
        let matchStatus = !status || rowStatus === status;
  
        $(this).toggle(matchSearch && matchBranch && matchStatus);
      });
    }
  
    $("#searchInput").on("keyup", filterTable);
    $("#branchFilter, #statusFilter").on("change", filterTable);

      // ✅ Export visible rows to CSV
  $("#exportCsv").on("click", function () {
    exportTableToCSV("members.csv");
  });

  function exportTableToCSV(filename) {
    let rows = [];

    // Header
    let headers = [];
    $("#membersTable thead th").each(function () {
      headers.push($(this).text().trim());
    });
    rows.push(headers);

    // Visible rows only (respects your filters)
    $("#membersTable tbody tr:visible").each(function () {
      let row = [];
      $(this).find("td").each(function () {
        row.push($(this).text().trim());
      });
      rows.push(row);
    });

    // Convert rows -> CSV string
    let csvContent = rows.map(r => r.map(csvEscape).join(",")).join("\n");

    // Download
    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);

    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);

    URL.revokeObjectURL(url);
  }

  function csvEscape(value) {
    if (value == null) return "";
    value = String(value).replace(/\r?\n|\r/g, " "); // remove new lines
    if (value.includes('"')) value = value.replace(/"/g, '""');
    if (value.includes(",") || value.includes('"')) value = `"${value}"`;
    return value;
  }

  
  });