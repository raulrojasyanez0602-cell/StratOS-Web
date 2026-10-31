function showSection(sectionId, btn) {
    console.log("Cambiando a sección:", sectionId); // Esto nos dirá en consola si el botón funciona

    // Ocultar todas las secciones
    const sections = document.querySelectorAll('main > section');
    sections.forEach(sec => {
        sec.classList.add('hidden');
        sec.classList.remove('block');
    });

    // Mostrar la seleccionada
    const activeSec = document.getElementById(`section-${sectionId}`);
    if(activeSec) {
        activeSec.classList.remove('hidden');
        activeSec.classList.add('block');
    }

    // Estilos de botones
    const buttons = document.querySelectorAll('.nav-btn');
    buttons.forEach(b => {
        b.classList.remove('bg-[#163A63]', 'text-[#56CCF2]', 'font-semibold');
        b.classList.add('text-[#91A4B7]');
    });
    if(btn) {
        btn.classList.remove('text-[#91A4B7]');
        btn.classList.add('bg-[#163A63]', 'text-[#56CCF2]', 'font-semibold');
    }
}