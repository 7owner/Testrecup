'use strict';

// Logiciel TIL V2 : porte « commande seule » sur un relais de MLR8 dans
// app/index.html (Playwright). FE1 a FE20.
// Fixture : porte 4 (A_N0_4, « Portail parking ») sur le relais 3 du MLR8 A9,
// relais XA0903, commande hyperviseur M28 (24 + 4). Aucun export Excel.
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const { chargerGenerator } = require('./helpers/charger-generator');
const fx = require('./helpers/fixtures');
const { demarrerApp, preparerPage, capturerPopup } = require('./helpers/page');

const TIL = chargerGenerator();
const OPTIONS = { timeout: 30000 };
const VIDE = ['', '-', '—'];

let app;
before(async () => { app = await demarrerApp(); });
after(async () => { if (app) await app.fermer(); });

async function avecPage(tillys, scenario) {
  const session = await preparerPage(app, tillys);
  try {
    return await scenario(session);
  } finally {
    await session.context.close();
  }
}

test('FE1 tableau d\'adresses : porte 4 raccordee, relais XA0903, commande M28, le reste vide', OPTIONS, async () => {
  await avecPage(fx.fixtureMlr8Commande(TIL), async ({ page }) => {
    const lignes = await page.evaluate(() => {
      renderTableauAdresses();
      return [...document.querySelectorAll('#addr-tbody tr')]
        .map(tr => [...tr.querySelectorAll('td')].map(td => td.textContent.replace(/\s+/g, ' ').trim()));
    });
    const porte4 = lignes.find(c => c[0] === '04');
    assert.ok(porte4, 'ligne de la porte 4 absente');
    assert.ok(porte4.length >= 20, `porte 4 affichee comme non raccordee : ${porte4.join(' | ')}`);
    assert.equal(porte4[8], 'XA0903', 'colonne Relais');
    assert.equal(porte4[16], 'M28', 'colonne M (cmd)');
    [4, 9, 10, 11, 12, 13, 14, 15, 17, 18, 19].forEach(i => {
      assert.ok(VIDE.includes(porte4[i]), `colonne ${i} de la porte 4 non vide : « ${porte4[i]} »`);
    });
    const voies = lignes.filter(c => c.some(v => v === 'XA0903'));
    assert.equal(voies.length, 1, 'XA0903 n\'apparait qu\'une fois (plus comme voie libre du MLR8)');
  });
});

test('FE2 export CSV : porte 4 Relais XA0903, CmdHyper M28 ; R3 du MLR8 n\'est plus une voie libre', OPTIONS, async () => {
  await avecPage(fx.fixtureMlr8Commande(TIL), async ({ page }) => {
    const csv = await page.evaluate(() => {
      window.__csv = null;
      window.telechargerContenu = contenu => { window.__csv = contenu; };
      exporterCSV();
      return window.__csv;
    });
    assert.equal(typeof csv, 'string', 'exporterCSV doit produire un contenu');
    const lignes = csv.split(/\r?\n/).filter(Boolean).map(l => l.split(';'));
    const entetes = lignes[0];
    const porte4 = lignes.find(c => c[1] === '4');
    assert.ok(porte4, 'ligne de la porte 4 absente du CSV');
    const col = nom => porte4[entetes.indexOf(nom)];
    assert.equal(col('Relais'), 'XA0903');
    assert.equal(col('CmdHyper'), 'M28');
    ['Lecteur', 'LED Verte', 'LED Rouge', 'Buzzer', 'BP', 'Etat Porte', 'DM', 'AP Boite CA', 'Timer', 'Effraction', 'POTL']
      .forEach(nom => assert.equal(col(nom), '', `porte 4 : colonne ${nom} vide`));
    assert.ok(!lignes.some(c => c[0] === 'MLR8 A9 R3'), 'voie R3 du MLR8 A9 encore listee comme libre');
    assert.ok(lignes.some(c => c[0] === 'MLR8 A9 R1'), 'les autres voies du MLR8 restent listees');
  });
});

test('FE3 fiche de la porte 4 : relais XA0903, commande M28, pas de timer', OPTIONS, async () => {
  await avecPage(fx.fixtureMlr8Commande(TIL), async ({ page }) => {
    const fiche = await page.evaluate(() => {
      voirDetailPorte(4, 0);
      if (typeof closeWiringUsagePopup === 'function') closeWiringUsagePopup();
      const body = document.getElementById('modal-body');
      const texte = body.textContent.replace(/\s+/g, ' ');
      fermerModal();
      return texte;
    });
    assert.ok(fiche.includes('XA0903'), 'relais XA0903 absent de la fiche');
    assert.ok(/\bM28\b/.test(fiche), 'commande M28 absente de la fiche');
    assert.ok(!/\bTN\d+/.test(fiche), `timer affiche pour une commande seule : ${fiche.match(/\bTN\d+/)}`);
  });
});

test('FE4 schema du MLR8 A9 : la porte 4 apparait sur son relais', OPTIONS, async () => {
  await avecPage(fx.fixtureMlr8Commande(TIL), async ({ page }) => {
    const vue = await page.evaluate(() => {
      voirDetailModule('MR9', 0);
      if (typeof closeWiringUsagePopup === 'function') closeWiringUsagePopup();
      const body = document.getElementById('modal-body');
      const texte = body.textContent.replace(/\s+/g, ' ');
      fermerModal();
      return texte;
    });
    assert.ok(vue.includes('XA0903'), 'precondition : registres du MLR8 affiches');
    assert.ok(vue.includes('A_N0_4') || vue.includes('Portail parking'), 'la porte 4 n\'apparait pas dans le schema du MLR8');
  });
});

test('FE5 carnet de cable : une seule ligne pour la porte 4, « CMD A_N0_4 » depuis le coffret / Tillys', OPTIONS, async () => {
  // BP / DM saisis a tort (import Excel) : une commande seule ne les cable pas.
  const t = fx.fixtureMlr8Commande(TIL);
  Object.assign(t.portes[3], { bp: 1, dm: 1 });
  await avecPage(t, async ({ page }) => {
    const lignes = await page.evaluate(() => buildCarnetCableRows()
      .map(r => ({ code: r.codeDepart, depart: r.depart, arrivee: r.arrivee })));
    const porte4 = lignes.filter(l => /A_N0_4$/.test(l.code) || l.arrivee === 'Portail parking');
    assert.deepEqual(porte4.map(l => l.code), ['CMD A_N0_4']);
    assert.match(porte4[0].depart, /Tillys 1/, 'la commande part du coffret / Tillys');
  });
});

test('FE6 (non-regression) consommation : la commande seule ne compte aucun lecteur', OPTIONS, async () => {
  await avecPage(fx.fixtureMlr8Commande(TIL), async ({ page }) => {
    const types = await page.evaluate(() => getCoffretDoorEquipmentItems(APP.tillys[0].portes[3]).map(i => i.type));
    assert.ok(!types.includes('Lecteur entrée') && !types.includes('Lecteur sortie'), `lecteur compte : ${types.join(' | ')}`);
  });
});

test('FE7 editeur : choisir « MLR8 A9 – R5 » fait de la porte 1 une commande seule sur XA0905', OPTIONS, async () => {
  await avecPage(fx.fixtureMlr8Commande(TIL), async ({ page }) => {
    const etat = await page.evaluate(() => {
      ouvrirPorteEditor(1, 'hardware');
      assignerPorteAuMlp2Draft('relais:MR9:5');
      validerPorteEditor();
      fermerPorteEditor();
      const t = getTillysActif();
      const porte = t.portes[0];
      const module = id => t.synopticModules.find(m => m.id === id);
      return {
        mr9: [...module('MR9').doorNums],
        ma1: [...module('MA1').doorNums],
        porte: {
          mlr8Relais: porte.mlr8Relais, mlp2ModuleId: porte.mlp2ModuleId,
          lecteurEntree: porte.lecteurEntree, lecteurSortie: porte.lecteurSortie,
          bp: Number(porte.bp), dm: Number(porte.dm), bap: Number(porte.barreAntiPanique),
        },
        lock: TIL.getPorteAddresses(t, 1).lock,
      };
    });
    assert.deepEqual(etat.mr9.sort((a, b) => a - b), [1, 4], 'porte 1 ajoutee au MLR8 A9');
    assert.ok(!etat.ma1.includes(1), 'porte 1 retiree du MLP2 A1');
    assert.deepEqual(etat.porte, {
      mlr8Relais: 5, mlp2ModuleId: '', lecteurEntree: '', lecteurSortie: '', bp: 0, dm: 0, bap: 0,
    });
    assert.equal(etat.lock, 'XA0905');
  });
});

test('FE8 synoptique : ajout sur le MLR8 au premier relais libre, retrait efface le relais', OPTIONS, async () => {
  const t = fx.fixtureMlr8Commande(TIL);
  Object.assign(t.portes[6], {
    active: true, designation: 'Barriere livraisons', batiment: 'A', etage: 'N0', numeroPorte: '7',
    verrouillage: 'CMD', lecteurEntree: '',
  });
  await avecPage(t, async ({ page }) => {
    const etat = await page.evaluate(() => {
      const tillys = getTillysActif();
      ajouterPorteAuModule('MR9', TIL.composerTriNumPorte(tillys.portes[6], 7), 0);
      const mr9 = () => [...tillys.synopticModules.find(m => m.id === 'MR9').doorNums];
      const apresAjout = { mr9: mr9(), relais7: tillys.portes[6].mlr8Relais, lock7: TIL.getPorteAddresses(tillys, 7).lock };
      retirerPorteDuModule('MR9', 4, 0);
      return { apresAjout, mr9: mr9(), relais4: tillys.portes[3].mlr8Relais, lock4: TIL.getPorteAddresses(tillys, 4).lock };
    });
    assert.deepEqual(etat.apresAjout.mr9, [4, 7], 'precondition : porte 7 ajoutee au MLR8 A9');
    assert.equal(etat.apresAjout.relais7, 1, 'porte 7 : premier relais libre (R3 pris par la porte 4)');
    assert.equal(etat.apresAjout.lock7, 'XA0901');
    assert.deepEqual(etat.mr9, [7], 'porte 4 retiree du MLR8');
    assert.ok(!etat.relais4, `porte 4 retiree : relais efface (obtenu ${etat.relais4})`);
    assert.equal(etat.lock4, '', 'porte 4 retiree : plus de relais');
  });
});

test('FE9 liste et code : commande seule non signalee « Sans MLP2 », code genere dans la page', OPTIONS, async () => {
  await avecPage(fx.fixtureMlr8Commande(TIL), async ({ page }) => {
    const etat = await page.evaluate(() => {
      const row = getProjetDoorRows({ activeOnly: true }).find(r => r.porte.num === 4);
      const qualite = getProjetDoorQuality(row);
      PROJECT_DOOR_LIST_UI.status = 'withoutMlp2';
      const sansMlp2 = filterProjetDoorRows(getProjetDoorRows({ activeOnly: true })).map(r => r.porte.num);
      PROJECT_DOOR_LIST_UI.status = 'all';
      showTab('tab-code');
      return {
        manquants: qualite.missing,
        sansMlp2,
        microcode: document.getElementById('microcode-output').value,
        srv: document.getElementById('srv-utl-output').value,
      };
    });
    assert.ok(!etat.manquants.includes('MLP2'), `porte 4 signalee sans MLP2 : ${etat.manquants.join(' | ')}`);
    assert.ok(etat.sansMlp2.includes(10), 'precondition : la porte 10 orpheline est bien « Sans MLP2 »');
    assert.ok(!etat.sansMlp2.includes(4), 'filtre « Sans MLP2 » : la porte 4 n\'y figure pas');
    assert.ok(etat.microcode.includes('EV(M28==1)'), 'microcode de la page : commande de la porte 4');
    assert.ok(etat.srv.includes('A_N0_4.cmd=M28'), 'serveur -> UTL de la page : A_N0_4.cmd=M28');
  });
});

// ── Second passage (revue) : sortie du relais de MLR8, projets existants ──

// Installe dans la page window.__choisirMl(valeur) : choisit une valeur dans le
// select « ML associé » de l'editeur ouvert comme l'utilisateur (valeur puis
// evenement change) et renvoie la valeur du select re-rendu.
async function installerChoisirMl(page) {
  await page.evaluate(() => {
    const trouver = () => [...document.querySelectorAll('#door-edit-body select')]
      .find(s => (s.getAttribute('onchange') || '').includes('assignerPorteAuMlp2Draft'));
    window.__selectMl = () => { const s = trouver(); return s ? s.value : null; };
    window.__choisirMl = valeur => {
      const select = trouver();
      if (!select) throw new Error('select « ML associé » introuvable');
      if (![...select.options].some(o => o.value === valeur)) {
        throw new Error(`option « ${valeur} » absente du select ML : ${[...select.options].map(o => o.value).join(' | ')}`);
      }
      select.value = valeur;
      select.dispatchEvent(new Event('change', { bubbles: true }));
      return window.__selectMl();
    };
  });
}

test('FE10 editeur : changer la porte 4 de bus la detache du MLR8 A9 (ni commande seule, ni mlr8ModuleId stocke)', OPTIONS, async () => {
  await avecPage(fx.fixtureMlr8Commande(TIL), async ({ page }) => {
    const etat = await page.evaluate(() => {
      const t = getTillysActif();
      const champsMlr8 = () => t.portes
        .map((p, i) => (p && Object.prototype.hasOwnProperty.call(p, 'mlr8ModuleId') ? `porte ${i + 1} = ${p.mlr8ModuleId}` : null))
        .filter(Boolean);
      const mr9 = () => [...t.synopticModules.find(m => m.id === 'MR9').doorNums];
      const auChargement = champsMlr8();
      ouvrirPorteEditor(4, 'hardware');
      changerPorteEditorBus('B');
      const num = PORTES_UI.editingNum;
      const apresChangement = { num, champs: champsMlr8(), designation: (t.portes[num - 1] || {}).designation };
      validerPorteEditor();
      fermerPorteEditor();
      const a = TIL.getPorteAddresses(t, num);
      return {
        auChargement,
        apresChangement,
        apresValidation: { champs: champsMlr8(), mr9: mr9(), bus: a.busAffichage, lock: a.lock, commandeSeule: !!a.commandeSeule },
      };
    });
    assert.deepEqual(etat.auChargement, [], 'precondition : aucune porte chargee ne porte mlr8ModuleId');
    const num = etat.apresChangement.num;
    assert.ok(num >= 9 && num <= 16, `precondition : la porte est deplacee sur le bus B (n° ${num})`);
    assert.equal(etat.apresChangement.designation, 'Portail parking', 'precondition : la porte deplacee garde sa designation');
    assert.deepEqual(etat.apresChangement.champs, [], 'apres changement de bus : mlr8ModuleId stocke dans tillys.portes');
    assert.deepEqual(etat.apresValidation.champs, [], 'apres validation : mlr8ModuleId stocke dans tillys.portes');
    assert.ok(!etat.apresValidation.mr9.includes(num), `porte ${num} raccrochee au MLR8 A9 : doorNums ${etat.apresValidation.mr9.join(',')}`);
    assert.ok(!etat.apresValidation.mr9.includes(4), `le MLR8 A9 garde l'ancien n° 4 : doorNums ${etat.apresValidation.mr9.join(',')}`);
    assert.equal(etat.apresValidation.commandeSeule, false, `porte ${num} encore commande seule (relais ${etat.apresValidation.lock})`);
    assert.ok(!/^XA09/.test(etat.apresValidation.lock), `porte ${num} encore pilotee par le MLR8 A9 : ${etat.apresValidation.lock}`);
    assert.equal(etat.apresValidation.bus, 'B', 'la porte deplacee est affichee sur le bus B');
  });
});

test('FE11 editeur : l\'option vide de « ML associé » retire la porte 4 du relais R3 (select vide)', OPTIONS, async () => {
  await avecPage(fx.fixtureMlr8Commande(TIL), async ({ page }) => {
    await installerChoisirMl(page);
    const etat = await page.evaluate(() => {
      const t = getTillysActif();
      ouvrirPorteEditor(4, 'hardware');
      const avant = window.__selectMl();
      const affiche = window.__choisirMl('');
      const brouillon = { mlr8Relais: PORTES_UI.editingDraft.mlr8Relais, mlr8ModuleId: PORTES_UI.editingDraft.mlr8ModuleId };
      validerPorteEditor();
      fermerPorteEditor();
      return {
        avant, affiche, brouillon,
        mr9: [...t.synopticModules.find(m => m.id === 'MR9').doorNums],
        lock: TIL.getPorteAddresses(t, 4).lock,
      };
    });
    assert.equal(etat.avant, 'relais:MR9:3', 'precondition : le select affiche le relais R3 a l\'ouverture');
    assert.ok(!etat.brouillon.mlr8Relais && !etat.brouillon.mlr8ModuleId, `precondition : le brouillon quitte le relais : ${JSON.stringify(etat.brouillon)}`);
    assert.equal(etat.affiche, '', `apres le choix vide, le select affiche encore « ${etat.affiche} »`);
    assert.ok(!etat.mr9.includes(4), 'apres validation : porte 4 retiree du MLR8 A9');
    assert.equal(etat.lock, '', 'apres validation : plus de relais');
  });
});

test('FE12 editeur : relais R5 puis retour sur le MLP2 A1 avant validation, la porte 1 retrouve LB, BP, DM', OPTIONS, async () => {
  await avecPage(fx.fixtureMlr8Commande(TIL), async ({ page }) => {
    await installerChoisirMl(page);
    const etat = await page.evaluate(() => {
      const t = getTillysActif();
      const champs = p => ({ lecteurEntree: p.lecteurEntree, bp: Number(p.bp), dm: Number(p.dm) });
      ouvrirPorteEditor(1, 'hardware');
      const avant = champs(PORTES_UI.editingDraft);
      const surRelais = window.__choisirMl('relais:MR9:5');
      const brouillonRelais = champs(PORTES_UI.editingDraft);
      const surMlp2 = window.__choisirMl('module:MA1');
      const brouillon = champs(PORTES_UI.editingDraft);
      validerPorteEditor();
      fermerPorteEditor();
      const stocke = champs(t.portes[0]);
      const a = TIL.getPorteAddresses(t, 1);
      showTab('tab-code');
      return {
        avant, surRelais, brouillonRelais, surMlp2, brouillon, stocke,
        lecteur: a.lecteur, commandeSeule: !!a.commandeSeule,
        ma1: [...t.synopticModules.find(m => m.id === 'MA1').doorNums],
        mr9: [...t.synopticModules.find(m => m.id === 'MR9').doorNums],
        microcode: document.getElementById('microcode-output').value,
      };
    });
    const attendu = { lecteurEntree: 'LB', bp: 1, dm: 1 };
    assert.deepEqual(etat.avant, attendu, 'precondition : porte 1 avec LB, BP et DM');
    assert.equal(etat.surRelais, 'relais:MR9:5', 'precondition : relais R5 choisi');
    assert.deepEqual(etat.brouillonRelais, { lecteurEntree: '', bp: 0, dm: 0 }, 'precondition : sur le relais, le brouillon est une commande seule');
    assert.equal(etat.surMlp2, 'module:MA1', 'precondition : retour sur le MLP2 A1');
    assert.deepEqual(etat.brouillon, attendu, 'brouillon : retour sur le MLP2, lecteur, BP et DM perdus');
    assert.deepEqual(etat.stocke, attendu, 'apres validation : lecteur, BP et DM perdus');
    assert.ok(etat.ma1.includes(1) && !etat.mr9.includes(1), `porte 1 sur le MLP2 A1 (MA1 ${etat.ma1}, MR9 ${etat.mr9})`);
    assert.equal(etat.commandeSeule, false, 'porte 1 n\'est plus une commande seule');
    assert.equal(etat.lecteur, 'LA1', 'porte 1 : lecteur LA1');
    assert.ok(etat.microcode.includes('EV(LA1==AUTORISE)'), 'microcode : evenement du lecteur LA1 absent');
  });
});

// Projet existant (v2.0.16) : porte 4 deja dans MR9.doorNums, saisie a tort
// avec un lecteur LB, un BP et un DM, sans mlr8Relais enregistre.
function fixtureMlr8Existant() {
  const t = fx.fixtureMlr8Commande(TIL);
  Object.assign(t.portes[3], { lecteurEntree: 'LB', bp: 1, dm: 1 });
  delete t.portes[3].mlr8Relais;
  return t;
}

test('FE13 projet existant, document Liste de porte : la commande seule n\'a pas de lecteur d\'entree (« - »)', OPTIONS, async () => {
  await avecPage(fixtureMlr8Existant(), async ({ context, page }) => {
    const commandeSeule = await page.evaluate(() => !!TIL.getPorteAddresses(getTillysActif(), 4).commandeSeule);
    assert.equal(commandeSeule, true, 'precondition : la porte 4 du MLR8 A9 est une commande seule');
    const popup = await capturerPopup(context, page, () => exporterListePortesPdf());
    const lignes = await popup.evaluate(() => {
      for (const table of document.querySelectorAll('table')) {
        const rangs = [...table.querySelectorAll('tr')].map(tr => [...tr.children].map(c => c.textContent.replace(/\s+/g, ' ').trim()));
        const i = rangs.findIndex(r => r[0] === 'N°Porte' && r[1] === 'Entrée' && r[2] === 'Sortie');
        if (i >= 0) return rangs.slice(i + 1);
      }
      return null;
    });
    assert.ok(lignes, 'tableau des lecteurs absent');
    assert.equal((lignes.find(l => l[0] === '1') || [])[1], 'LB', 'precondition : porte 1 avec un lecteur LB');
    const porte4 = lignes.find(l => l[0] === '4');
    assert.ok(porte4, 'porte 4 absente du tableau des lecteurs');
    assert.equal(porte4[1], '-', `porte 4 commande seule : Entrée « ${porte4[1]} »`);
  });
});

test('FE14 projet existant, liste des portes : ni BP, ni DM, ni POTL, ni Effraction pour la commande seule ; Cmd Hyperviseur reste', OPTIONS, async () => {
  await avecPage(fixtureMlr8Existant(), async ({ page }) => {
    const badges = await page.evaluate(() => {
      showTab('tab-liste-portes');
      const lire = n => {
        const article = [...document.querySelectorAll('#liste-portes-container article.project-door-soft-row')]
          .find(a => (a.getAttribute('onclick') || '').replace(/\s+/g, '') === `ouvrirPorteDepuisProjet(0,${n})`);
        return article ? [...article.querySelectorAll('.badge.badge-standard')].map(b => b.textContent.trim()) : null;
      };
      return { 1: lire(1), 4: lire(4) };
    });
    assert.ok(badges[1] && badges[4], 'precondition : lignes des portes 1 et 4 rendues');
    assert.ok(badges[1].includes('BP') && badges[1].includes('DM'), `precondition : badges BP / DM de la porte 1 : ${badges[1].join(' | ')}`);
    ['BP', 'DM', 'POTL', 'Effraction'].forEach(b => {
      assert.ok(!badges[4].includes(b), `porte 4 commande seule : badge « ${b} » affiche (${badges[4].join(' | ')})`);
    });
    assert.ok(badges[4].includes('Cmd Hyperviseur'), `porte 4 : badge « Cmd Hyperviseur » absent (${badges[4].join(' | ')})`);
  });
});

test('FE15 projet existant, consommation : la commande seule ne compte ni lecteur, ni BP, ni DM', OPTIONS, async () => {
  await avecPage(fixtureMlr8Existant(), async ({ page }) => {
    const types = await page.evaluate(() => ({
      porte1: getCoffretDoorEquipmentItems(APP.tillys[0].portes[0]).map(i => i.type),
      porte4: getCoffretDoorEquipmentItems(APP.tillys[0].portes[3]).map(i => i.type),
    }));
    assert.ok(types.porte1.includes('Lecteur entrée') && types.porte1.includes('BP') && types.porte1.includes('DM'),
      `precondition : la porte 1 compte lecteur, BP et DM : ${types.porte1.join(' | ')}`);
    ['Lecteur entrée', 'Lecteur sortie', 'BP', 'DM'].forEach(type => {
      assert.ok(!types.porte4.includes(type), `porte 4 commande seule : « ${type} » compte (${types.porte4.join(' | ')})`);
    });
  });
});

// ── Seconde revue : affichages de la porte existante, sorties de relais ──

test('FE16 projet existant, liste des portes : colonne « Entrée » de la commande seule a « - » et aucun « N° »', OPTIONS, async () => {
  await avecPage(fixtureMlr8Existant(), async ({ page }) => {
    const entrees = await page.evaluate(() => {
      showTab('tab-liste-portes');
      const lire = n => {
        const article = [...document.querySelectorAll('#liste-portes-container article.project-door-soft-row')]
          .find(a => (a.getAttribute('onclick') || '').replace(/\s+/g, '') === `ouvrirPorteDepuisProjet(0,${n})`);
        if (!article) return null;
        const cellule = [...article.querySelectorAll('.project-door-soft-cell')]
          .find(c => (c.querySelector('.project-door-soft-label') || {}).textContent === 'Entrée');
        if (!cellule) return null;
        return {
          lecteur: (cellule.querySelector('strong') || {}).textContent,
          petits: [...cellule.querySelectorAll('small')].map(s => s.textContent.replace(/\s+/g, ' ').trim()),
        };
      };
      return {
        1: lire(1),
        4: lire(4),
        commandeSeule: !!TIL.getPorteAddresses(getTillysActif(), 4).commandeSeule,
      };
    });
    assert.equal(entrees.commandeSeule, true, 'precondition : la porte 4 du MLR8 A9 est une commande seule');
    assert.ok(entrees[1] && entrees[4], 'precondition : colonnes « Entrée » des portes 1 et 4 rendues');
    assert.equal(entrees[1].lecteur, 'LB', 'precondition : la porte 1 affiche son lecteur LB');
    assert.ok(entrees[1].petits.some(s => s.startsWith('N°')), `precondition : la porte 1 affiche son N° : ${entrees[1].petits.join(' | ')}`);
    assert.equal(entrees[4].lecteur, '-', `porte 4 commande seule : Entrée « ${entrees[4].lecteur} »`);
    assert.ok(!entrees[4].petits.some(s => s.startsWith('N°')), `porte 4 commande seule : « ${entrees[4].petits.join(' | ')} » affiche`);
  });
});

test('FE17 projet existant, arbre des portes : aucune etiquette « LB » pour la commande seule', OPTIONS, async () => {
  await avecPage(fixtureMlr8Existant(), async ({ page }) => {
    const etiquettes = await page.evaluate(() => {
      PORTES_UI.view = 'list';
      PORTES_UI.busFilter = 'ALL';
      renderTableauPortes();
      const lire = n => {
        const feuille = [...document.querySelectorAll('#portes-tree-root article.porte-tree-leaf')]
          .find(a => [...a.querySelectorAll('button')].some(b => (b.getAttribute('onclick') || '').replace(/\s+/g, '') === `ouvrirPorteEditor(${n})`));
        return feuille ? [...feuille.querySelectorAll('.porte-app-tag')].map(s => s.textContent.trim()) : null;
      };
      return { 1: lire(1), 4: lire(4) };
    });
    assert.ok(etiquettes[1] && etiquettes[4], 'precondition : feuilles des portes 1 et 4 rendues');
    assert.ok(etiquettes[1].includes('LB'), `precondition : la porte 1 porte l'etiquette LB : ${etiquettes[1].join(' | ')}`);
    assert.ok(etiquettes[4].includes('CMD'), `precondition : etiquette de verrouillage CMD de la porte 4 : ${etiquettes[4].join(' | ')}`);
    assert.ok(!etiquettes[4].includes('LB'), `porte 4 commande seule : etiquette « LB » affichee (${etiquettes[4].join(' | ')})`);
  });
});

test('FE18 editeur : relais R5 puis changement de bus avant validation, la porte 1 retrouve LB, BP, DM et quitte le relais', OPTIONS, async () => {
  await avecPage(fx.fixtureMlr8Commande(TIL), async ({ page }) => {
    await installerChoisirMl(page);
    const etat = await page.evaluate(() => {
      const t = getTillysActif();
      const champs = p => ({ lecteurEntree: p.lecteurEntree, bp: Number(p.bp), dm: Number(p.dm) });
      ouvrirPorteEditor(1, 'hardware');
      const avant = champs(PORTES_UI.editingDraft);
      const surRelais = window.__choisirMl('relais:MR9:5');
      const brouillonRelais = champs(PORTES_UI.editingDraft);
      changerPorteEditorBus('B');
      const num = PORTES_UI.editingNum;
      validerPorteEditor();
      fermerPorteEditor();
      const porte = t.portes[num - 1];
      const a = TIL.getPorteAddresses(t, num);
      return {
        avant, surRelais, brouillonRelais, num,
        designation: porte.designation,
        stocke: champs(porte),
        mlr8Relais: porte.mlr8Relais,
        commandeSeule: !!a.commandeSeule,
        bus: a.busAffichage,
        mr9: [...t.synopticModules.find(m => m.id === 'MR9').doorNums],
      };
    });
    const attendu = { lecteurEntree: 'LB', bp: 1, dm: 1 };
    assert.deepEqual(etat.avant, attendu, 'precondition : porte 1 avec LB, BP et DM');
    assert.equal(etat.surRelais, 'relais:MR9:5', 'precondition : relais R5 choisi');
    assert.deepEqual(etat.brouillonRelais, { lecteurEntree: '', bp: 0, dm: 0 }, 'precondition : sur le relais, le brouillon est une commande seule');
    assert.ok(etat.num >= 9 && etat.num <= 16, `precondition : la porte est deplacee sur le bus B (n° ${etat.num})`);
    assert.equal(etat.designation, 'Local Velos', 'precondition : la porte deplacee garde sa designation');
    assert.equal(etat.bus, 'B', 'precondition : la porte deplacee est sur le bus B');
    assert.deepEqual(etat.stocke, attendu, 'apres changement de bus et validation : lecteur, BP et DM perdus');
    assert.ok(!etat.mlr8Relais, `la porte deplacee garde un relais de MLR8 (${etat.mlr8Relais})`);
    assert.equal(etat.commandeSeule, false, 'la porte deplacee est encore une commande seule');
    assert.ok(!etat.mr9.includes(1) && !etat.mr9.includes(etat.num), `porte raccrochee au MLR8 A9 : doorNums ${etat.mr9.join(',')}`);
  });
});

// Charge plusieurs Tillys d'un coup (chargerTillys n'en charge qu'un).
async function chargerProjet(page, tillysListe) {
  const donnees = JSON.parse(JSON.stringify(tillysListe));
  const ok = await page.evaluate(liste => {
    const resultat = chargerDepuisJSON({ version: '2.0', projet: { nom: 'TEST' }, options: APP.options, tillys: liste });
    APP.tillysActif = 0;
    return resultat;
  }, donnees);
  assert.equal(ok, true, 'chargerDepuisJSON doit accepter la fixture');
}

test('FE19 editeur : relais R5 puis changement de Tillys avant validation, la porte 1 retrouve LB, BP, DM et quitte le relais', OPTIONS, async () => {
  const session = await preparerPage(app, null);
  try {
    const { page } = session;
    await chargerProjet(page, [fx.fixtureMlr8Commande(TIL), TIL.creerTillys(1, 'Tillys 2')]);
    await installerChoisirMl(page);
    const etat = await page.evaluate(() => {
      const champs = p => ({ lecteurEntree: p.lecteurEntree, bp: Number(p.bp), dm: Number(p.dm) });
      const nbTillys = APP.tillys.length;
      ouvrirPorteEditor(1, 'hardware');
      const avant = champs(PORTES_UI.editingDraft);
      const surRelais = window.__choisirMl('relais:MR9:5');
      const brouillonRelais = champs(PORTES_UI.editingDraft);
      changerPorteEditorDeTillys('1');
      const actif = APP.tillysActif;
      const num = PORTES_UI.editingNum;
      validerPorteEditor();
      fermerPorteEditor();
      const cible = APP.tillys[1];
      const porte = cible.portes[num - 1];
      return {
        nbTillys, avant, surRelais, brouillonRelais, actif, num,
        designation: porte.designation,
        stocke: champs(porte),
        mlr8Relais: porte.mlr8Relais,
        commandeSeule: !!TIL.getPorteAddresses(cible, num).commandeSeule,
        mr9: [...APP.tillys[0].synopticModules.find(m => m.id === 'MR9').doorNums],
      };
    });
    const attendu = { lecteurEntree: 'LB', bp: 1, dm: 1 };
    assert.equal(etat.nbTillys, 2, 'precondition : deux Tillys charges');
    assert.deepEqual(etat.avant, attendu, 'precondition : porte 1 avec LB, BP et DM');
    assert.equal(etat.surRelais, 'relais:MR9:5', 'precondition : relais R5 choisi');
    assert.deepEqual(etat.brouillonRelais, { lecteurEntree: '', bp: 0, dm: 0 }, 'precondition : sur le relais, le brouillon est une commande seule');
    assert.equal(etat.actif, 1, 'precondition : la porte est deplacee vers le Tillys 2');
    assert.equal(etat.designation, 'Local Velos', 'precondition : la porte deplacee garde sa designation');
    assert.deepEqual(etat.stocke, attendu, 'apres changement de Tillys et validation : lecteur, BP et DM perdus');
    assert.ok(!etat.mlr8Relais, `la porte deplacee garde un relais de MLR8 (${etat.mlr8Relais})`);
    assert.equal(etat.commandeSeule, false, 'la porte deplacee est encore une commande seule');
    assert.ok(!etat.mr9.includes(1), `porte 1 encore sur le MLR8 A9 du Tillys 1 : doorNums ${etat.mr9.join(',')}`);
  } finally {
    await session.context.close();
  }
});

test('FE20 editeur : un MLP2 plein refuse la porte 4 commande seule sans lui faire perdre son relais', OPTIONS, async () => {
  // Projet existant : sans mlr8Relais stocke, le generateur attribue le premier relais libre (R1).
  const cas = [['nouveau projet', fx.fixtureMlr8Commande(TIL), 3], ['projet existant', fixtureMlr8Existant(), 1]];
  for (const [nom, fixture, relais] of cas) {
    await avecPage(fixture, async ({ page }) => {
      const etat = await page.evaluate(() => {
        const t = getTillysActif();
        const ma1Avant = [...t.synopticModules.find(m => m.id === 'MA1').doorNums];
        ouvrirPorteEditor(4, 'hardware');
        const select = [...document.querySelectorAll('#door-edit-body select')]
          .find(s => (s.getAttribute('onchange') || '').includes('assignerPorteAuMlp2Draft'));
        const optionMa1 = select ? [...select.options].find(o => o.value === 'module:MA1') : null;
        const draft = PORTES_UI.editingDraft;
        const avant = { mlr8ModuleId: draft.mlr8ModuleId, mlr8Relais: draft.mlr8Relais };
        const resultat = appliquerAffectationMlp2Draft(t, draft, 4, 'module:MA1');
        const apres = {
          mlr8ModuleId: draft.mlr8ModuleId, mlr8Relais: draft.mlr8Relais,
          mlp2ModuleId: draft.mlp2ModuleId || '', mlp2Attribue: draft.mlp2Attribue || '',
        };
        if (typeof fermerResolutionConflitMlp2 === 'function') fermerResolutionConflitMlp2();
        validerPorteEditor();
        fermerPorteEditor();
        return {
          ma1Avant,
          ma1Complet: optionMa1 ? optionMa1.disabled : null,
          avant, resultat, apres,
          lock: TIL.getPorteAddresses(t, 4).lock,
          mr9: [...t.synopticModules.find(m => m.id === 'MR9').doorNums],
        };
      });
      assert.deepEqual(etat.ma1Avant, [1, 3], `${nom} : precondition : le MLP2 A1 a deja ses deux portes`);
      assert.equal(etat.ma1Complet, true, `${nom} : precondition : le MLP2 A1 est affiche complet dans « ML associé »`);
      assert.deepEqual(etat.avant, { mlr8ModuleId: 'MR9', mlr8Relais: relais }, `${nom} : precondition : le brouillon est sur le relais R${relais} du MLR8 A9`);
      assert.equal(etat.resultat, false, `${nom} : le MLP2 A1 plein doit etre refuse`);
      assert.deepEqual(etat.apres, { mlr8ModuleId: 'MR9', mlr8Relais: relais, mlp2ModuleId: '', mlp2Attribue: '' },
        `${nom} : brouillon apres refus du MLP2`);
      assert.equal(etat.lock, `XA090${relais}`, `${nom} : apres validation, la porte 4 a perdu son relais`);
      assert.ok(etat.mr9.includes(4), `${nom} : apres validation, porte 4 retiree du MLR8 A9 : doorNums ${etat.mr9.join(',')}`);
    });
  }
});
