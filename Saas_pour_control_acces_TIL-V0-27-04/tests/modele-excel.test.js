'use strict';

// Modele Excel de l'auto-control : il est copie a chaque export, il ne doit donc
// transporter aucune donnee d'un ancien chantier. Ses macros (CopierValeurs,
// MettreAJourToutesImages) appellent des feuilles par leur nom : elles doivent rester.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const { getRacineApp } = require('./helpers/racine');

const XLSX = require(path.join(getRacineApp(), 'app', 'vendor', 'xlsx.full.min.js'));
const MODELE = path.join(getRacineApp(), 'Documentation sur le projet', 'PROG TIL VIERGE TEST (version reçue) (version 2)_fauche.xlsm');
const DONNEES_CHANTIER = /SARTOR|\bP17\b|P17[-_]|ARCHIVE|LUDO/i;

function lireModele() {
  return XLSX.read(fs.readFileSync(MODELE), { bookVBA: true, bookSST: true });
}

test('M1 modele auto-control : aucune donnee de chantier dans les cellules ni dans les chaines', () => {
  const wb = lireModele();
  const trouvees = [];
  wb.SheetNames.forEach(nom => {
    const ws = wb.Sheets[nom];
    Object.keys(ws).filter(ref => ref[0] !== '!').forEach(ref => {
      const valeur = ws[ref].v;
      if (typeof valeur === 'string' && DONNEES_CHANTIER.test(valeur)) trouvees.push(`${nom}!${ref}=${valeur}`);
    });
  });
  assert.deepEqual(trouvees.slice(0, 10), [], `${trouvees.length} cellule(s) avec des donnees de chantier`);
  const chaines = (wb.Strings || []).map(s => s && s.t).filter(t => t && DONNEES_CHANTIER.test(t));
  assert.deepEqual(chaines.slice(0, 10), [], 'chaines partagees orphelines encore presentes');
});

test('M2 modele auto-control : feuilles appelees par les macros et en-tetes conserves', () => {
  const wb = lireModele();
  ['MODELES', 'LISTE DE PORTE', 'Programmation', 'CARNET DE CABLE ', 'P17 - TILLYS 02 (RDC)', 'Fiche auto control']
    .forEach(nom => assert.ok(wb.SheetNames.includes(nom), `feuille « ${nom} » absente`));
  assert.ok(wb.vbaraw && wb.vbaraw.length > 0, 'projet VBA absent');
  const valeur = (feuille, ref) => (wb.Sheets[feuille][ref] || {}).v;
  assert.equal(valeur('LISTE DE PORTE', 'D2'), 'N°PORTE');
  assert.equal(valeur('CARNET DE CABLE ', 'A1'), 'TYPE DE CABLE');
  assert.equal(valeur('P17 - TILLYS 02 (RDC)', 'B3'), 'TILLYS 01 / BUS A / MLP2 A1', 'texte lu par la macro CopierValeurs');
  assert.equal(valeur('Fiche auto control', 'A13'), 'PORTE');
  // Les lignes d'exemple sont vides.
  assert.equal(valeur('LISTE DE PORTE', 'A3'), undefined);
  assert.equal(valeur('Fiche auto control', 'A15'), undefined);
});
