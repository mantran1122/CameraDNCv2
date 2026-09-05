import codecs
with codecs.open('static/js/app.js', 'r', 'utf-8', errors='ignore') as f:
    content = f.read()

target1 = '''            ${hasClip ? `<button class="btn-clip-play" onclick="openClipModal(${ev.id}, '${ev.clip_filename}', '${ev.description}')">'''

repl1 = '''            ${hasClip ? `<button class="btn-clip-play" onclick="openClipModal(${ev.id})">'''

target2 = '''// Modal Clip Player
async function openClipModal(eventId, clipFilename, description) {
    document.getElementById('modal-event-title').innerText = description;
    
    const videoElem = document.getElementById('modal-video-player');
    const sourceElem = document.getElementById('modal-video-source');
    
    sourceElem.src = `/clips/${clipFilename}`;
    videoElem.load();
    videoElem.play().catch(e => console.log('Autoplay prevented:', e));

    try {
        const res = await fetch(`/api/events/${eventId}`);
        const ev = await res.json();
        
        document.getElementById('clip-detail-ch').innerText = `Ch ${String(ev.channel).padStart(2, '0')}`;
        document.getElementById('clip-detail-time').innerText = ev.timestamp;
        document.getElementById('clip-detail-type').innerText = `${ev.event_code} (${ev.event_type})`;
        document.getElementById('clip-detail-audio').innerText = ev.audio_level_db ? `${ev.audio_level_db} dB` : 'N/A';
    } catch(e) {}

    document.getElementById('videoModal').classList.add('active');
}'''

repl2 = '''// Modal Clip Player
async function openClipModal(eventId) {
    try {
        const res = await fetch(`/api/events/${eventId}`);
        const ev = await res.json();
        
        document.getElementById('modal-event-title').innerText = ev.description;
        
        const videoElem = document.getElementById('modal-video-player');
        const sourceElem = document.getElementById('modal-video-source');
        
        sourceElem.src = `/clips/${ev.clip_filename}`;
        videoElem.load();
        videoElem.play().catch(e => console.log('Autoplay prevented:', e));

        document.getElementById('clip-detail-ch').innerText = `Ch ${String(ev.channel).padStart(2, '0')}`;
        document.getElementById('clip-detail-time').innerText = ev.timestamp;
        document.getElementById('clip-detail-type').innerText = `${ev.event_code} (${ev.event_type})`;
        document.getElementById('clip-detail-audio').innerText = ev.audio_level_db ? `${ev.audio_level_db} dB` : 'N/A';
        
        document.getElementById('videoModal').classList.add('active');
    } catch(e) {
        console.error('Error opening clip modal:', e);
    }
}'''

if target1 in content and target2 in content:
    content = content.replace(target1, repl1)
    content = content.replace(target2, repl2)
    with codecs.open('static/js/app.js', 'w', 'utf-8') as f:
        f.write(content)
    print('SUCCESS')
else:
    print('TARGET NOT FOUND')
