
const resumeInput = document.getElementById("resumeFile");
const fileName = document.getElementById("fileName");
const analyzeBtn = document.getElementById("analyzeBtn");

resumeInput.addEventListener("change", function () {

    const file = this.files[0];

    if (!file) {
        return;
    }

    const allowedTypes = [
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ];

    if (!allowedTypes.includes(file.type)) {
        alert("Please upload only PDF or DOCX files.");
        this.value = "";
        analyzeBtn.disabled = true;
        fileName.textContent = "Maximum file size: 5 MB";
        return;
    }

    if (file.size > 5 * 1024 * 1024) {
        alert("File size should not exceed 5 MB.");
        this.value = "";
        analyzeBtn.disabled = true;
        fileName.textContent = "Maximum file size: 5 MB";
        return;
    }

    fileName.textContent = "Selected: " + file.name;
    analyzeBtn.disabled = false;
});

analyzeBtn.addEventListener("click", function () {
    alert("Resume selected successfully! Flask analysis backend will be connected in the next step.");
});

const criteriaForm = document.getElementById("criteriaForm");

if (criteriaForm) {

    criteriaForm.addEventListener("submit", function(event) {

        event.preventDefault();

        const jobData = {
            jobTitle: document.getElementById("jobTitle").value,
            companyName: document.getElementById("companyName").value,
            education: document.getElementById("education").value,
            experience: document.getElementById("experience").value,
            requiredSkills: document.getElementById("requiredSkills").value,
            jobDescription: document.getElementById("jobDescription").value
        };

        localStorage.setItem("jobCriteria", JSON.stringify(jobData));

        document.getElementById("saveMessage").textContent =
            "Job Criteria saved successfully!";
    });

    const savedCriteria = localStorage.getItem("jobCriteria");

    if (savedCriteria) {

        const jobData = JSON.parse(savedCriteria);

        document.getElementById("jobTitle").value = jobData.jobTitle || "";
        document.getElementById("companyName").value = jobData.companyName || "";
        document.getElementById("education").value = jobData.education || "";
        document.getElementById("experience").value = jobData.experience || "";
        document.getElementById("requiredSkills").value = jobData.requiredSkills || "";
        document.getElementById("jobDescription").value = jobData.jobDescription || "";
    }
}
