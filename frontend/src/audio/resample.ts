export function downsampleTo16k(input: Float32Array, inputSampleRate: number): Float32Array {
  const outputSampleRate = 16000;
  if (inputSampleRate === outputSampleRate) {
    return input;
  }
  if (inputSampleRate < outputSampleRate) {
    throw new Error(`Input sample rate ${inputSampleRate} is lower than 16kHz.`);
  }

  const ratio = inputSampleRate / outputSampleRate;
  const outputLength = Math.floor(input.length / ratio);
  const output = new Float32Array(outputLength);

  for (let index = 0; index < outputLength; index += 1) {
    const sourceIndex = index * ratio;
    const left = Math.floor(sourceIndex);
    const right = Math.min(left + 1, input.length - 1);
    const weight = sourceIndex - left;
    output[index] = input[left] * (1 - weight) + input[right] * weight;
  }

  return output;
}

