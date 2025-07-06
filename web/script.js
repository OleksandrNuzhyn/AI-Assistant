const canvas = document.getElementById('visualizerCanvas');
const ctx = canvas.getContext('2d');
const statusText = document.getElementById('statusText');
const container = document.querySelector('.container');
const abortButton = document.getElementById('abortButton');

const timerText = document.getElementById('timerText');
let listeningStartTime = null;
let timerInterval = null;

let width = canvas.width = window.innerWidth;
let height = canvas.height = window.innerHeight;

window.addEventListener('resize', () => {
    width = canvas.width = window.innerWidth;
    height = canvas.height = window.innerHeight;
});

const nodes = [];
const numNodes = 14;
const connectionDistance = 100;
const baseSpeed = 0.2;

let assistantState = 'idle';
let typewriting_interval = null;

class Node {
    constructor() {
        this.x = Math.random() * width;
        this.y = Math.random() * height;
        this.vx = (Math.random() - 0.5) * baseSpeed;
        this.vy = (Math.random() - 0.5) * baseSpeed;
        this.radius = Math.random() * 2.5 + 1.5;
        this.baseRadius = this.radius;
        this.pulseSpeed = Math.random() * 0.05 + 0.01;
        this.pulseAngle = Math.random() * Math.PI * 2;
    }

    update() {
        let speedMultiplier = 1.0;

        switch (assistantState) {
            case 'listening':
                this.radius = this.baseRadius * (1.5 + Math.sin(this.pulseAngle) * 0.5);
                break;
            case 'processing':
                speedMultiplier = 4.0;
                this.radius = this.baseRadius * (1 + Math.sin(this.pulseAngle * 3) * 0.3);
                break;
            case 'speaking':
                 this.radius = this.baseRadius * (2.0 + Math.sin(Date.now() * 0.01) * 0.7);
                break;
            case 'idle':
            default:
                 this.radius = this.baseRadius * (1 + Math.sin(this.pulseAngle) * 0.2);
                break;
        }
        
        this.pulseAngle += this.pulseSpeed;

        this.x += this.vx * speedMultiplier;
        this.y += this.vy * speedMultiplier;

        if (this.x < 0 || this.x > width) this.vx *= -1;
        if (this.y < 0 || this.y > height) this.vy *= -1;
    }

    draw() {
        ctx.beginPath();
        ctx.arc(this.x, this.y, this.radius, 0, Math.PI * 2);
        ctx.fillStyle = 'rgba(180, 220, 255, 0.7)';
        ctx.fill();
    }
}

function createNodes() {
    for (let i = 0; i < numNodes; i++) {
        nodes.push(new Node());
    }
}

function drawConnections() {
    for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
            const dx = nodes[i].x - nodes[j].x;
            const dy = nodes[i].y - nodes[j].y;
            const distance = Math.sqrt(dx * dx + dy * dy);

            if (distance < connectionDistance) {
                ctx.beginPath();
                ctx.moveTo(nodes[i].x, nodes[i].y);
                ctx.lineTo(nodes[j].x, nodes[j].y);
                const opacity = 1 - (distance / connectionDistance);
                ctx.strokeStyle = `rgba(180, 220, 255, ${opacity * 0.3})`;
                ctx.lineWidth = 1;
                ctx.stroke();
            }
        }
    }
}

function animate() {
    ctx.clearRect(0, 0, width, height);
    nodes.forEach(node => {
        node.update();
        node.draw();
    });
    drawConnections();
    requestAnimationFrame(animate);
}

function typewriterEffect(element, text) {
    if (typewriting_interval) {
        clearInterval(typewriting_interval);
    }
    
    let i = 0;
    element.innerHTML = "";
    
    typewriting_interval = setInterval(() => {
        if (i < text.length) {
            element.innerHTML += text.charAt(i);
            i++;
        } else {
            clearInterval(typewriting_interval);
        }
    }, 35);
}

window.updateStatus = function(text, state) {
    if (state === 'listening') {
        listeningStartTime = Date.now();
        if (timerInterval) clearInterval(timerInterval);

        timerText.innerText = '0:00';
        timerInterval = setInterval(() => {
            const elapsed = Date.now() - listeningStartTime;
            const sec = Math.floor(elapsed / 1000);
            const m = Math.floor(sec / 60);
            const s = sec % 60;
            timerText.innerText = m + ':' + String(s).padStart(2, '0');
        }, 1000);
    } else {
        if (timerInterval) clearInterval(timerInterval);
        timerText.innerText = '';
    }
    assistantState = state;
    typewriterEffect(statusText, text);

    if (state !== 'idle') {
        statusText.classList.add('active');
        container.classList.add('active');
        if (!text.startsWith('Завантаження')) {
            abortButton.classList.add('visible');
        } else {
            abortButton.classList.remove('visible');
        }
    } else {
        statusText.classList.remove('active');
        container.classList.remove('active');
        abortButton.classList.remove('visible');
    }
};

abortButton.addEventListener('click', () => {
    console.log('Abort button clicked!');
    if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.abort_current_task === 'function') {
        console.log('Calling abort_current_task via pywebview API');
        window.pywebview.api.abort_current_task();
    } else if (typeof window.abort_current_task === 'function') {
        console.log('Calling fallback abort_current_task');
        window.abort_current_task();
    } else {
        console.error('CRITICAL: abort_current_task not exposed on window or pywebview.api');
    }
});

createNodes();
animate(); 