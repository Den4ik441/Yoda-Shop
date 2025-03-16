import React from 'react';
import { CreditCard, Star, Send, Code, ChevronRight } from 'lucide-react';

const Services = () => {
  const services = [
    {
      icon: <CreditCard size={32} className="text-yoda-green" />,
      title: "ininal",
      description: "Secure digital payment solutions and card services. Fast, reliable, and user-friendly.",
      features: ["Secure transactions", "Easy activation", "24/7 support", "Multiple payment options"]
    },
    {
      icon: <Star size={32} className="text-yoda-green" />,
      title: "Stars Telegram Premium",
      description: "Enhance your Telegram experience with premium features and exclusive benefits.",
      features: ["Priority access", "Ad-free experience", "Double upload limits", "Exclusive stickers"]
    },
    {
      icon: <Send size={32} className="text-yoda-green" />,
      title: "Telegram Services",
      description: "Professional Telegram channel management and promotion services.",
      features: ["Channel growth", "Content strategy", "Analytics", "Customer engagement"]
    },
    {
      icon: <Code size={32} className="text-yoda-green" />,
      title: "Programming Solutions",
      description: "Custom software development and programming services tailored to your needs.",
      features: ["Custom development", "Web applications", "Mobile solutions", "Technical consultation"]
    }
  ];

  return (
    <section id="services" className="py-20 px-6 md:px-8 relative overflow-hidden gradient-bg">
      <div className="max-w-7xl mx-auto">
        <div className="text-center mb-16 opacity-0 animate-slide-up">
          <h2 className="section-heading">Our Services</h2>
          <p className="section-subheading max-w-2xl mx-auto">
            Discover our range of high-quality digital services designed to meet your needs
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
          {services.map((service, index) => (
            <div 
              key={index} 
              className="service-card opacity-0 animate-slide-up"
              style={{ animationDelay: `${index * 100}ms` }}
            >
              <div className="flex items-start gap-4">
                <div className="p-3 rounded-xl bg-primary/10">
                  {service.icon}
                </div>
                <div>
                  <h3 className="text-xl font-medium mb-2">{service.title}</h3>
                  <p className="text-muted-foreground mb-4">{service.description}</p>
                  
                  <ul className="space-y-2">
                    {service.features.map((feature, idx) => (
                      <li key={idx} className="flex items-center gap-2">
                        <ChevronRight size={16} className="text-yoda-green" />
                        <span className="text-sm">{feature}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
};

export default Services;
