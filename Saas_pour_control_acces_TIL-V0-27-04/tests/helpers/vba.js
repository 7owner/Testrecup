'use strict';

// Lecture du code source VBA d'un classeur (vbaProject.bin), sans Excel :
// conteneur OLE lu par XLSX.CFB, modules decompresses au format MS-OVBA.

function decompresser(data) {
  if (!data.length || data[0] !== 1) throw new Error('flux VBA compresse invalide');
  const sortie = [];
  let pos = 1;
  while (pos < data.length) {
    const entete = data[pos] | (data[pos + 1] << 8);
    const finBloc = Math.min(pos + (entete & 0x0fff) + 3, data.length);
    const compresse = (entete & 0x8000) !== 0;
    pos += 2;
    const debut = sortie.length;
    if (!compresse) {
      for (let i = 0; i < 4096 && pos < data.length; i += 1) sortie.push(data[pos++]);
      continue;
    }
    while (pos < finBloc) {
      const drapeaux = data[pos++];
      for (let bit = 0; bit < 8 && pos < finBloc; bit += 1) {
        if (((drapeaux >> bit) & 1) === 0) {
          sortie.push(data[pos++]);
          continue;
        }
        const jeton = data[pos] | (data[pos + 1] << 8);
        pos += 2;
        const d = sortie.length - debut;
        const nbBits = Math.max(Math.ceil(Math.log2(Math.max(d, 1))), 4);
        const longueur = (jeton & (0xffff >> nbBits)) + 3;
        const decalage = (jeton >> (16 - nbBits)) + 1;
        for (let i = 0; i < longueur; i += 1) sortie.push(sortie[sortie.length - decalage]);
      }
    }
  }
  return Buffer.from(sortie);
}

function vbaSource(XLSX, vbaraw) {
  const cfb = XLSX.CFB.read(Buffer.from(vbaraw), { type: 'buffer' });
  const flux = nom => {
    const entree = XLSX.CFB.find(cfb, `/${nom}`);
    if (!entree) throw new Error(`flux ${nom} absent du projet VBA`);
    return Buffer.from(entree.content);
  };
  const dir = decompresser(flux('VBA/dir'));
  const modules = [];
  let pos = 0;
  let nom = null;
  while (pos + 6 <= dir.length) {
    const id = dir.readUInt16LE(pos);
    const taille = id === 0x0009 ? 6 : dir.readUInt32LE(pos + 2);
    const corps = dir.subarray(pos + 6, pos + 6 + taille);
    if (id === 0x001a) nom = corps.toString('latin1');
    if (id === 0x0031 && nom) { modules.push([nom, corps.readUInt32LE(0)]); nom = null; }
    pos += 6 + taille;
  }
  return modules
    .map(([module, offset]) => decompresser(flux(`VBA/${module}`).subarray(offset)).toString('latin1'))
    .join('\n');
}

module.exports = { vbaSource };
