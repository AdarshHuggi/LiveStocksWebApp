document.addEventListener('DOMContentLoaded', function () {
  const nav = document.querySelector('.navbar');

  if (nav) {
    window.addEventListener('scroll', function () {
      if (window.scrollY > 20) {
        nav.classList.add('scrolled');
      } else {
        nav.classList.remove('scrolled');
      }
    });
  }

  const search = document.querySelector('#animalSearch');
  const species = document.querySelector('#speciesFilter');
  const gender = document.querySelector('#genderFilter');
  const results = [...document.querySelectorAll('.animal-result')];
  if (search && species && gender) {
    [...new Set(results.map((item) => item.dataset.species))].filter(Boolean).sort().forEach((value) => {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = value.charAt(0).toUpperCase() + value.slice(1);
      species.append(option);
    });
    const filterAnimals = () => {
      let visible = 0;
      results.forEach((item) => {
        const match = item.dataset.search.includes(search.value.trim().toLowerCase()) &&
          (!species.value || item.dataset.species === species.value) &&
          (!gender.value || item.dataset.gender === gender.value);
        item.hidden = !match;
        if (match) visible += 1;
      });
      const empty = document.querySelector('#noAnimalsFound');
      if (empty) empty.hidden = visible > 0;
    };
    [search, species, gender].forEach((control) => control.addEventListener('input', filterAnimals));
  }

  const calculatorInputs = ['birthCount', 'offspringValue'].map((id) => document.getElementById(id));
  const estimate = document.getElementById('estimatedShare');
  if (calculatorInputs.every(Boolean) && estimate) {
    const formatRupees = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 });
    const calculate = () => {
      const count = Math.max(0, Number(calculatorInputs[0].value) || 0);
      const value = Math.max(0, Number(calculatorInputs[1].value) || 0);
      estimate.textContent = formatRupees.format(count * value * 0.5);
    };
    calculatorInputs.forEach((input) => input.addEventListener('input', calculate));
    calculate();
  }
});
