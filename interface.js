document.addEventListener("DOMContentLoaded", () => {
    const displayStyleSelect = document.getElementById('displayStyle');
    const relevanceSliderContainer = document.getElementById('relevanceSliderContainer');
    const relevanceThreshold = document.getElementById('relevanceThreshold');
    const relevanceValue = document.getElementById('relevanceValue');
    const statusLabel = document.getElementById('status-label');
    let statusElement = document.getElementById('status');
    let startTaskButton = document.getElementById('startTask');
    let previousDisplayStyle = null; 
    let initialTask = null;
    let newThreshold = null;
    let previousThreshold = null;

    // setting dynamic relevance threshold for only task-specific display style
    relevanceThreshold.addEventListener('input', function () {
        newThreshold = this.value;
        relevanceValue.textContent = newThreshold;
    });

    // initial task update
    startTaskButton.addEventListener('click', () => {
        let taskInput = document.getElementById("taskUpdate").value.trim();
        const currentStyle = displayStyleSelect.value;

        if (taskInput === "") return;
        
        if (displayStyleSelect.value === 'less-opacity' || displayStyleSelect.value === 'color-gradient') {
            relevanceThreshold.value = 0;
        }  

        parameters = {
            displayStyle: displayStyleSelect.value,
            relevanceThreshold: relevanceThreshold.value,
            status: statusElement.innerText
        }

        // case 1: task changed
        if (initialTask !== taskInput) {
            console.log("Task changed → sending taskUpdate");
    
            chrome.runtime.sendMessage({ message: 'taskUpdate', data: taskInput, parameters }, (response) => {
                statusLabel.classList.remove('hidden');
                statusElement.innerText = "Processing...";
                console.log('Popup received response:', response.reply);
            });
    
            initialTask = taskInput;
            previousDisplayStyle = currentStyle;
            startTaskButton.innerText = "Update task";
            document.getElementById("completeTask").classList.remove("hidden");
    
        // case 2: style changed, task unchanged
        } else if (statusElement.innerText === "Page updated.") {
            if (previousDisplayStyle !== currentStyle) {
                console.log("Display style changed → sending updateDisplayStyle");
                chrome.runtime.sendMessage({
                    message: 'updateDisplayStyle',
                    task: taskInput,
                    parameters
                });
                previousDisplayStyle = currentStyle;
            } 
            // case 3: task unchanged, style unchanged, relevance threshold changed
            else if (previousDisplayStyle === currentStyle && previousThreshold != newThreshold) {
                console.log("Relevance threshold changed → sending updateDisplayStyle");
                relevanceThreshold.value = newThreshold;
                console.log("parameters: ", parameters);
                chrome.runtime.sendMessage({
                    message: 'updateDisplayStyle',
                    task: taskInput,
                    parameters
                });
                previousThreshold = newThreshold;
            }
            console.log("previousDisplayStyle: ", previousDisplayStyle, " currentStyle: ", currentStyle, " relevanceThreshold: ", relevanceThreshold.value, " newThreshold: ", newThreshold);
        } 
        
        
    
        startTaskButton.disabled = true;
    });

    // action for completing the task
    document.getElementById('completeTask').addEventListener('click', () => {
        completeTask(parameters);
    });

    
    // changing the rendering style of the task-relevant elements
    displayStyleSelect.addEventListener('change', function () {
        if (this.value === 'task-specific') {
            relevanceThreshold.value = 70;
            relevanceSliderContainer.classList.remove('hidden');
        } else if (this.value === 'less-opacity' || this.value === 'color-gradient') {
            relevanceThreshold.value = 0;
            relevanceSliderContainer.classList.add('hidden');
        }
    }); 
})

// change status when page is updated with task-relevant elements
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === 'page-updated') {
        document.getElementById("status").innerText = "Page updated.";
        document.getElementById("startTask").disabled = false;
    }
});

// function to complete the task
function completeTask(parameters) {
    document.getElementById("status").innerText = "Task completed!";
    chrome.runtime.sendMessage({ message: 'task-completed' }, (response) => {
        console.log('Response for task completion: ', response.reply);
    });
    setTimeout(() => {
        window.close();
    }, 500);
}
