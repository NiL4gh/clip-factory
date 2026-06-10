import React from 'react';

interface Props {
  headerText: string;
  headerFont: string;
  captionText: string;
  captionFont: string;
  hookText: string;
  hookFont: string;
  bgStyle: 'black' | 'brand' | 'blur' | 'white';
}

export const ClipPreview: React.FC<Props> = ({
  headerText, headerFont, captionText, captionFont, hookText, hookFont, bgStyle
}) => {
  const bgMap = {
    black: 'bg-black',
    brand: 'bg-slate-900',
    blur: 'bg-black/80 backdrop-blur-xl',
    white: 'bg-white'
  };

  const textColor = bgStyle === 'white' ? 'text-slate-900' : 'text-white';
  const mutedColor = bgStyle === 'white' ? 'text-slate-400' : 'text-white/30';

  return (
    <div className={`relative w-[260px] h-[462px] ${bgMap[bgStyle]} rounded-2xl overflow-hidden border border-[var(--border-color)] shadow-2xl mx-auto transition-all duration-300`}>
      {/* Video simulation */}
      <div className={`absolute top-12 left-1/2 -translate-x-1/2 w-[230px] h-[230px] rounded-xl border-2 border-dashed flex items-center justify-center ${bgStyle === 'white' ? 'bg-slate-50 border-slate-200' : 'bg-white/5 border-white/15'}`}>
        <span className={`text-[10px] font-medium ${mutedColor}`}>Video Content Area</span>
      </div>

      {/* Hook — first 3s */}
      <div className="absolute top-3 left-1/2 -translate-x-1/2 text-center w-[94%] z-10">
        <span
          className={`${textColor} text-lg font-bold leading-tight block`}
          style={{
            fontFamily: hookFont,
            WebkitTextStroke: '1px rgba(0,0,0,0.7)',
            textShadow: '2px 2px 6px rgba(0,0,0,0.6), 0 0 20px rgba(0,0,0,0.3)'
          }}
        >
          {hookText || 'YOUR HOOK TEXT'}
        </span>
      </div>

      {/* Header — appears at 3.5s */}
      <div className="absolute top-[260px] left-1/2 -translate-x-1/2 text-center w-[90%] px-2 z-10">
        <span
          className={`${textColor} text-sm font-bold drop-shadow-lg`}
          style={{ fontFamily: headerFont }}
        >
          {headerText || 'Header Title'}
        </span>
      </div>

      {/* Caption — bottom */}
      <div className="absolute bottom-10 left-1/2 -translate-x-1/2 text-center w-[96%] px-2 z-10">
        <span
          className={`${textColor} text-[11px] leading-relaxed px-2 py-1 rounded-md ${bgStyle === 'white' ? 'bg-black/5' : 'bg-black/30 backdrop-blur-sm'}`}
          style={{ fontFamily: captionFont }}
        >
          {captionText || 'Caption text preview showing selected font style'}
        </span>
      </div>

      {/* Progress bar simulation */}
      <div className={`absolute bottom-0 left-0 right-0 h-1 ${bgStyle === 'white' ? 'bg-slate-200' : 'bg-white/10'}`}>
        <div className={`h-full ${bgStyle === 'white' ? 'bg-blue-500' : 'bg-white/60'} w-1/3 rounded-r`} />
      </div>
    </div>
  );
};
