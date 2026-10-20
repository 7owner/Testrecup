'use strict';

// Modele Excel de l'auto-control : il est copie a chaque export, il ne doit donc
// transporter aucune donnee d'un ancien chantier. Ses macros (CopierValeurs,
// MettreAJourToutesImages) appellent des feuilles par leur nom : elles doivent rester.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const { getRacineApp } = require('./helpers/racine');
const vba = require('./helpers/vba');

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
  ['MODELES', 'LISTE DE PORTE', 'Programmation', 'CARNET DE CABLE ', 'TILLYS 02 (RDC)', 'Fiche auto control']
    .forEach(nom => assert.ok(wb.SheetNames.includes(nom), `feuille « ${nom} » absente`));
  // Le nom de feuille porte lui aussi le chantier d'origine : il a ete retire (macros adaptees).
  assert.deepEqual(wb.SheetNames.filter(nom => DONNEES_CHANTIER.test(nom)), [], 'nom de feuille avec donnee de chantier');
  // Les macros appellent la feuille par son nom : le code VBA doit citer le nouveau nom, plus l'ancien.
  const code = vba.vbaSource(XLSX, wb.vbaraw);
  assert.ok(code.includes('Sub CopierValeurs') && code.includes('Sub MettreAJourToutesImages'), 'macros du modele introuvables');
  assert.ok(code.includes('Sheets("TILLYS 02 (RDC)")'), 'macro sans le nouveau nom de feuille');
  assert.ok(!code.includes('P17 - TILLYS'), 'macro encore sur l\'ancien nom de feuille');
  // Macros utiles hors generation : evenements de feuille et d'ouverture conserves.
  ['Sub Workbook_Open', 'Sub Worksheet_SelectionChange', 'Sub Worksheet_Activate', 'Sub GererImage']
    .forEach(proc => assert.ok(code.includes(proc), `macro « ${proc} » absente`));
  // Macros mortes retirees : Macro1 (Enregistrer sous vers un poste nominatif) et
  // Image2_Cliquer (visait une feuille « Feuil1 » inexistante, rattachee a aucune forme).
  assert.ok(!code.includes('Sub Macro1') && !code.includes('lguais'), 'Macro1 encore presente');
  assert.ok(!code.includes('Image2_Cliquer'), 'Image2_Cliquer encore presente');
  assert.ok(wb.vbaraw && wb.vbaraw.length > 0, 'projet VBA absent');
  const valeur = (feuille, ref) => (wb.Sheets[feuille][ref] || {}).v;
  assert.equal(valeur('LISTE DE PORTE', 'D2'), 'N°PORTE');
  assert.equal(valeur('CARNET DE CABLE ', 'A1'), 'TYPE DE CABLE');
  assert.equal(valeur('TILLYS 02 (RDC)', 'B3'), 'TILLYS 01 / BUS A / MLP2 A1', 'texte lu par la macro CopierValeurs');
  assert.equal(valeur('Fiche auto control', 'A13'), 'PORTE');
  // Les lignes d'exemple sont vides.
  assert.equal(valeur('LISTE DE PORTE', 'A3'), undefined);
  assert.equal(valeur('Fiche auto control', 'A15'), undefined);
});
